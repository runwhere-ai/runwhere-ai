"""Kubernetes Pod list/watch adapter feeding ``SharedInformer``.

Provides the ``(list_fn, watch_fn)`` callables the informer needs (spec FR-100/101),
backed by a real ``kubernetes_asyncio`` Pod watch. We watch **Pods** (not the
controllers) so that pod-level status transitions — Running, ImagePullBackOff,
OOMKilled, CrashLoopBackOff … — surface immediately on the detail page.

Each Pod is normalised into the flat dict shape the informer/UI expect:
``{namespace, name, pod_name, resource_version, labels, display_status}`` where
``name`` is the owning workload (controller) name read from the
``job-name`` / ``app`` label, so it matches the detail page object id
``status-{ns}-{kind}-{name}``. ``display_status`` is pre-computed with the same
rules the list uses, so the WS layer renders a badge without touching raw K8s.
"""
from __future__ import annotations

import logging
from typing import Any

from src.console.models import Kind

logger = logging.getLogger(__name__)

JOB_TYPE_LABEL = "runwhere.ai/job-type"


def _display_status(pod_status: Any) -> str:
    """Derive the user-facing status from a Pod status (same rules as the list)."""
    from gpuctl.constants import get_detailed_status

    phase = getattr(pod_status, "phase", None) or "Unknown"
    for cs in (getattr(pod_status, "container_statuses", None) or []):
        state = getattr(cs, "state", None)
        if not state:
            continue
        waiting = getattr(state, "waiting", None)
        if waiting:
            return get_detailed_status(
                getattr(waiting, "reason", "") or "",
                getattr(waiting, "message", "") or "",
            )
        terminated = getattr(state, "terminated", None)
        if terminated:
            reason = getattr(terminated, "reason", "") or ""
            if reason == "OOMKilled":
                return "OOMKilled"
            if reason == "Error":
                return "Error"
            break
    return phase


def _controller_name(labels: dict[str, str]) -> str | None:
    # training (K8s Job) → job-name=<name>; inference/notebook/compute → app=<name>
    return labels.get("job-name") or labels.get("app")


def normalize_pod(pod: Any) -> dict[str, Any]:
    """V1Pod → flat dict the informer/UI consume. Keyed by the controller name."""
    meta = pod.metadata
    labels = dict(meta.labels or {})
    return {
        "namespace": meta.namespace,
        "name": _controller_name(labels) or meta.name,
        "pod_name": meta.name,
        "resource_version": meta.resource_version,
        "labels": labels,
        "display_status": _display_status(pod.status),
    }


def make_pod_adapter(kind: Kind):
    """Return ``(list_fn, watch_fn)`` watching Pods labeled for ``kind``.

    Both create + tear down a fresh ApiClient per call so the aiohttp session is
    never leaked across the informer's relist/rewatch cycles.
    """
    selector = f"{JOB_TYPE_LABEL}={kind.value}"

    async def list_fn() -> tuple[list[dict[str, Any]], str]:
        from kubernetes_asyncio import client
        from src.console.k8s_config import load_k8s_config

        await load_k8s_config()
        v1 = client.CoreV1Api()
        try:
            resp = await v1.list_pod_for_all_namespaces(label_selector=selector)
            items = [normalize_pod(p) for p in resp.items]
            return items, resp.metadata.resource_version
        finally:
            await v1.api_client.close()

    async def watch_fn(rv: str):
        from kubernetes_asyncio import client, watch
        from kubernetes_asyncio.client.exceptions import ApiException
        from src.console.informer import _GoneError
        from src.console.k8s_config import load_k8s_config

        await load_k8s_config()
        v1 = client.CoreV1Api()
        w = watch.Watch()
        try:
            async for event in w.stream(
                v1.list_pod_for_all_namespaces,
                label_selector=selector,
                resource_version=rv or None,
                timeout_seconds=300,
            ):
                typ = event.get("type")
                if typ == "ERROR":
                    # Usually 410 GONE (rv too old) → tell the informer to relist.
                    raise _GoneError()
                pod = event["object"]
                yield {
                    "type": typ,
                    "object": normalize_pod(pod),
                    "resource_version": pod.metadata.resource_version,
                }
        except ApiException as exc:
            if getattr(exc, "status", None) == 410:
                raise _GoneError() from exc
            raise
        finally:
            w.stop()
            await v1.api_client.close()

    return list_fn, watch_fn
