"""轻量任务队列元数据 —— v1「提交就睡」。

队列状态全部寄存在 K8s Job 对象上(`spec.suspend` + runwhere.ai/* 标签),**无数据库**。
v1 不做自动准入、不维护内存账本、不替 K8s/device-plugin 选卡;这里只保留
队列视图和手动放行所需的标签解析与排序。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

# 队列标签(寄存在 Job 上,重启 list 一遍即重建队列)
LBL_QUEUED = "runwhere.ai/queued"          # "true"
LBL_STATE = "runwhere.ai/queue-state"      # pending / admitted / running / done / unschedulable
LBL_PRIORITY = "runwhere.ai/priority"      # high / medium / low
LBL_POOL = "runwhere.ai/pool"
LBL_GPU = "runwhere.ai/gpu-request"
LBL_OWNER = "runwhere.ai/owner"            # 公平份额 key(= namespace)
ANN_SUBMITTED = "runwhere.ai/submitted-at"  # RFC3339 —— 注解(非标签:label 值不允许冒号)

PRIORITY_RANK = {"high": 0, "medium": 1, "low": 2}


@dataclass
class QueuedJob:
    namespace: str
    name: str
    priority: str
    gpus: int
    pool: str
    owner: str
    submitted_at: str            # RFC3339,排序用(空串排最后)
    state: str = "pending"

    @property
    def _sort_key(self) -> tuple:
        return (PRIORITY_RANK.get(self.priority, 1), self.submitted_at or "~")


# ── 纯逻辑 ───────────────────────────────────────────────────────────────────────
def order_pending(jobs: list[QueuedJob]) -> list[QueuedJob]:
    """排序键:优先级降序(high→low)→ 提交时间升序(FIFO,兼防饿死)。"""
    return sorted(jobs, key=lambda j: j._sort_key)


# ── 从 K8s Job 对象解析队列元数据 ────────────────────────────────────────────────
def queued_job_from_labels(namespace: str, name: str, labels: dict[str, str],
                           suspend: bool, annotations: Optional[dict[str, str]] = None
                           ) -> Optional[QueuedJob]:
    """带 runwhere.ai/queued=true 标签的 Job → QueuedJob;否则 None。
    state 优先用标签;标签缺失时由 suspend 推断(suspend=true→pending)。
    submitted-at 从【注解】读(label 值不允许冒号)。"""
    labels = labels or {}
    annotations = annotations or {}
    if labels.get(LBL_QUEUED) != "true":
        return None
    try:
        gpus = int(labels.get(LBL_GPU, "0"))
    except ValueError:
        gpus = 0
    state = labels.get(LBL_STATE) or ("pending" if suspend else "running")
    return QueuedJob(
        namespace=namespace, name=name,
        priority=labels.get(LBL_PRIORITY, "medium"),
        gpus=gpus,
        pool=labels.get(LBL_POOL, "default"),
        owner=labels.get(LBL_OWNER, namespace),
        submitted_at=annotations.get(ANN_SUBMITTED, ""),
        state=state,
    )


def _ensure_k8s_config(state: dict) -> None:
    from kubernetes import config
    if state.get("cfg"):
        return
    try:
        config.load_incluster_config()
    except Exception:  # noqa: BLE001
        try:
            config.load_kube_config()
        except Exception:  # noqa: BLE001
            pass
    state["cfg"] = True
