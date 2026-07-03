"""轻量任务队列单测 —— v1 只保留排序和 K8s Job 标签解析。"""

from src.console.job_queue import (
    QueuedJob,
    order_pending,
    queued_job_from_labels,
)


def _j(name, priority="medium", gpus=1, pool="default", submitted="2026-06-28T10:00:00Z"):
    return QueuedJob(namespace="ml", name=name, priority=priority, gpus=gpus,
                     pool=pool, owner="ml", submitted_at=submitted)


def test_order_priority_then_fifo():
    jobs = [
        _j("a", "low", submitted="2026-06-28T09:00:00Z"),
        _j("b", "high", submitted="2026-06-28T10:00:00Z"),
        _j("c", "high", submitted="2026-06-28T09:30:00Z"),
        _j("d", "medium", submitted="2026-06-28T08:00:00Z"),
    ]
    ordered = [j.name for j in order_pending(jobs)]
    # high(按提交时间:c 早于 b)→ medium(d)→ low(a)
    assert ordered == ["c", "b", "d", "a"]


def test_queued_job_from_labels():
    labels = {
        "runwhere.ai/queued": "true",
        "runwhere.ai/priority": "high",
        "runwhere.ai/gpu-request": "4",
        "runwhere.ai/pool": "h100",
        "runwhere.ai/owner": "ml-team",
        "runwhere.ai/queue-state": "pending",
    }
    # submitted-at 在【注解】里(label 值不允许冒号)
    anns = {"runwhere.ai/submitted-at": "2026-06-28T10:00:00Z"}
    j = queued_job_from_labels("ml-team", "bob-sft", labels, suspend=True, annotations=anns)
    assert j is not None
    assert (j.priority, j.gpus, j.pool, j.state) == ("high", 4, "h100", "pending")
    assert j.submitted_at == "2026-06-28T10:00:00Z"


def test_queued_job_from_labels_ignores_non_queue_jobs():
    assert queued_job_from_labels("ns", "n", {"app": "foo"}, suspend=False) is None


def test_queued_job_from_labels_infers_running_when_unsuspended_without_state():
    labels = {"runwhere.ai/queued": "true", "runwhere.ai/gpu-request": "1"}
    j = queued_job_from_labels("ns", "n", labels, suspend=False)
    assert j is not None
    assert j.state == "running"
