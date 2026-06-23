"""Unit tests for the Pod→informer normalization + status derivation.

The real kubernetes_asyncio watch can only be exercised against a live cluster
(verify on runw); here we test the deterministic normalization that turns a V1Pod
into the flat dict the informer/UI consume, and the display-status derivation.
"""
from __future__ import annotations

import types

from src.console.k8s_watch import _display_status, normalize_pod


def _cs(waiting_reason=None, waiting_msg="", terminated_reason=None):
    state = types.SimpleNamespace(
        waiting=(types.SimpleNamespace(reason=waiting_reason, message=waiting_msg)
                 if waiting_reason else None),
        terminated=(types.SimpleNamespace(reason=terminated_reason)
                    if terminated_reason else None),
    )
    return types.SimpleNamespace(state=state, ready=False)


def _pod(name="p-abc", ns="default", rv="100", labels=None, phase="Running", css=None):
    return types.SimpleNamespace(
        metadata=types.SimpleNamespace(namespace=ns, name=name, resource_version=rv, labels=labels or {}),
        status=types.SimpleNamespace(phase=phase, container_statuses=css or []),
    )


def test_display_status_running():
    assert _display_status(_pod().status) == "Running"


def test_display_status_image_pull_backoff():
    p = _pod(phase="Pending", css=[_cs(waiting_reason="ImagePullBackOff")])
    assert _display_status(p.status) == "ImagePullBackOff"


def test_display_status_oomkilled():
    p = _pod(phase="Failed", css=[_cs(terminated_reason="OOMKilled")])
    assert _display_status(p.status) == "OOMKilled"


def test_normalize_uses_controller_name_from_job_name_label():
    p = _pod(name="axolotl-ft-abc12",
             labels={"job-name": "axolotl-ft", "runwhere.ai/job-type": "training"},
             phase="Failed")
    d = normalize_pod(p)
    assert d["name"] == "axolotl-ft"          # controller name → matches detail page id
    assert d["pod_name"] == "axolotl-ft-abc12"
    assert d["namespace"] == "default"
    assert d["resource_version"] == "100"
    assert d["display_status"] == "Failed"


def test_normalize_uses_app_label_for_services():
    p = _pod(name="llm-prod-7f-x", labels={"app": "llm-prod"})
    assert normalize_pod(p)["name"] == "llm-prod"


def test_normalize_falls_back_to_pod_name_without_label():
    assert normalize_pod(_pod(name="lonepod", labels={}))["name"] == "lonepod"
