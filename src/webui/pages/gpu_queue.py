"""任务队列(看自己排第几)—— 设计 #3「提交就睡」的队列视图。

数据来源:K8s Job 对象上的 `runwhere.ai/queued=true` 标签。
v1 只有队列视图和手动放行，不启动自动 admission loop。
"""
from __future__ import annotations

from datetime import datetime, timezone
import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from src.console.job_queue import (
    LBL_QUEUED,
    LBL_STATE,
    QueuedJob,
    _ensure_k8s_config,
    order_pending,
    queued_job_from_labels,
)
from src.console.models import User
from src.webui.deps import get_current_user
from src.webui.templating import templates

router = APIRouter(tags=["gpu-queue"])
logger = logging.getLogger("src.webui.pages.gpu_queue")


def _waited(submitted_at: str, running: bool) -> str:
    try:
        ts = datetime.fromisoformat((submitted_at or "").replace("Z", "+00:00"))
        secs = (datetime.now(timezone.utc) - ts).total_seconds()
    except (ValueError, TypeError):
        return "—"
    if secs < 0:
        secs = 0
    if secs < 3600:
        human = f"{int(secs // 60)} 分钟"
    else:
        human = f"{secs / 3600:.1f} 小时"
    return f"已运行 {human}" if running else human


def _row(j, pos, state) -> dict:
    if state == "unschedulable":
        reason = f"要 {j.gpus} 卡，超过 {j.pool} 池上限 — 改请求或换池"
    elif state == "pending":
        reason = "排队中（等空闲卡）"
    else:
        reason = None
    return {
        "pos": pos, "namespace": j.namespace, "name": j.name,
        "owner": j.owner, "priority": j.priority,
        "gpus": j.gpus, "pool": j.pool, "waited": _waited(j.submitted_at, state == "running"),
        "state": state, "reason": reason, "cards": None,
    }


def _queue_to_view(jobs: list[QueuedJob]) -> dict:
    pending = order_pending([j for j in jobs if j.state == "pending"])
    running = [j for j in jobs if j.state in ("admitted", "running")]
    unsched = [j for j in jobs if j.state == "unschedulable"]
    rows = (
        [_row(j, i, "pending") for i, j in enumerate(pending, 1)]
        + [_row(j, None, "running") for j in running]
        + [_row(j, None, "unschedulable") for j in unsched]
    )
    return {"rows": rows, "pending_n": len(pending), "running_n": len(running)}


def list_queued_jobs() -> tuple[list[QueuedJob], str | None]:
    """Read queued Jobs directly from Kubernetes.

    Returns (jobs, error). The page must not block product use if the cluster is
    absent in local dev; unknown is better than fake queue data.
    """
    try:
        from kubernetes import client

        state = {"cfg": False}
        _ensure_k8s_config(state)
        batch = client.BatchV1Api()
        resp = batch.list_job_for_all_namespaces(
            label_selector=f"{LBL_QUEUED}=true",
            _request_timeout=(1, 2),
        )
        jobs: list[QueuedJob] = []
        for j in resp.items:
            qj = queued_job_from_labels(
                j.metadata.namespace,
                j.metadata.name,
                j.metadata.labels or {},
                bool(getattr(j.spec, "suspend", False)),
                j.metadata.annotations or {},
            )
            if qj:
                jobs.append(qj)
        return jobs, None
    except Exception as exc:  # noqa: BLE001
        logger.warning("queued job list unavailable: %s", exc)
        return [], str(exc)


def queued_counts() -> tuple[int, int, bool]:
    """Return (pending, unschedulable, available) for dashboard summary."""
    jobs, err = list_queued_jobs()
    if err:
        return 0, 0, False
    pending = sum(1 for j in jobs if j.state == "pending")
    unsched = sum(1 for j in jobs if j.state == "unschedulable")
    return pending, unsched, True


def release_queued_job(namespace: str, name: str) -> None:
    """Manual v1 release: flip suspend=false and mark admitted."""
    from kubernetes import client

    state = {"cfg": False}
    _ensure_k8s_config(state)
    body = {
        "metadata": {"labels": {LBL_STATE: "admitted"}},
        "spec": {"suspend": False},
    }
    client.BatchV1Api().patch_namespaced_job(
        name=name,
        namespace=namespace,
        body=body,
        _request_timeout=(1, 2),
    )


@router.get("/queue")
async def gpu_queue(request: Request, user: User = Depends(get_current_user)):
    jobs, err = list_queued_jobs()
    data = _queue_to_view(jobs)
    return templates.TemplateResponse(
        request, "pages/gpu_queue.html",
        {"user": user, **data, "queue_error": err, "queue_available": err is None}
    )


@router.post("/queue/{namespace}/{name}/release")
async def release_queue_job(namespace: str, name: str,
                            user: User = Depends(get_current_user)):
    try:
        release_queued_job(namespace, name)
        return JSONResponse({"ok": True})
    except Exception as exc:  # noqa: BLE001
        logger.warning("release queued job %s/%s failed: %s", namespace, name, exc)
        return JSONResponse({"ok": False, "detail": str(exc)}, status_code=500)
