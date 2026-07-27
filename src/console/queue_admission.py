"""队列自动准入 —— job-queue-design v1「提交就睡」的最后一环:从停车场变真队列。

三条克制原则(与 docs/design/job-queue-design.md 一致,写代码前先钉死):
  1. **空闲判定只信 prober 的真实占用**(`gpu_prober.STORE`),绝不看 K8s allocation——
     time-slicing 下"还剩几份"不代表还有显存、env 钉卡的任务故意不声明 `nvidia.com/gpu`、
     非托管 docker 负载在 K8s 账本上根本不存在。三种情况都会让 K8s 账本"看起来空闲"但
     实际满载,所以唯一可信的信号是 prober 实测的 `PhysicalGpu.state`。
  2. **一次只放一个在途任务**:放行后要等 prober 确认它真的落地占卡(或超时兜底),
     才评估下一个候选——否则"检查空闲→放行"和"pod 真正拉镜像/占住显存"之间有窗口期,
     两个任务会挤同一张卡。
  3. **不确定就不放**:拿不到 prober 数据、拿不到节点列表时,一律当"不知道",宁可让
     任务多睡一轮,不猜。

不加数据库、不加调度器、不加 webhook——一个后台线程,复用 job_queue.py 已有的
list_queued_jobs / order_pending / release_queued_job,新增的只是"何时该放行"这一个判断。
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Optional

from src.console.job_queue import (
    _ensure_k8s_config,
    list_queued_jobs,
    order_pending,
    release_queued_job,
)

logger = logging.getLogger(__name__)

_k8s_config_state: dict = {"cfg": False}


def _pool_node_names(pool: str) -> Optional[set[str]]:
    """pool -> 该池节点名集合(含未打 `runwhere.ai/pool` 标签、落回 default 池的节点)。

    刻意不用 gpuctl 的 `PoolClient.get_pool()`——它对 "default" 池的 label_selector
    精确匹配 `runwhere.ai/pool=default`,查不到"从未显式打过标签"的节点(见
    `PoolClient.list_pools()` 用 dict.get 兜底、`get_pool()` 没有,这是既有的不一致)。
    这里直接按 `list_pools()` 同款语义(未打标签 → "default")自己分桶,对 runw 这种
    单节点/从未建过池的场景才对。

    K8s 不可达时返回 None——调用方必须把 None 当"不知道",不能当"没有节点"。
    """
    try:
        from gpuctl.constants import Labels
        from kubernetes import client

        _ensure_k8s_config(_k8s_config_state)
        nodes = client.CoreV1Api().list_node(_request_timeout=(1, 2))
    except Exception as exc:  # noqa: BLE001
        logger.debug("queue-admission: list_node failed: %s", exc)
        return None
    return {
        n.metadata.name for n in nodes.items
        if (n.metadata.labels or {}).get(Labels.POOL, "default") == pool
    }


def free_gpu_count(pool: str) -> Optional[int]:
    """prober 视角下,该 pool 节点集合里「真正空闲」(state=='free')的物理卡数。

    None = 不知道(prober 无数据 / 节点列表拿不到)——调用方必须保守地不放行。
    """
    from src.console.gpu_prober import STORE

    node_names = _pool_node_names(pool)
    if not node_names:
        return None
    snapshot = STORE.snapshot()
    if not snapshot:
        return None
    return sum(
        1
        for node, data in snapshot.items()
        if node in node_names
        for gpu in data.get("gpus", [])
        if gpu.state == "free"
    )


def _job_has_landed(namespace: str, name: str) -> bool:
    """prober 是否已经看到这个 job 的进程真的落地占卡(managed 归因命中该 namespace/name)。"""
    from src.console.gpu_prober import STORE

    for data in STORE.snapshot().values():
        for gpu in data.get("gpus", []):
            for proc in gpu.processes:
                if proc.kind == "managed" and proc.pod_namespace == namespace and proc.pod_name == name:
                    return True
    return False


class AdmissionLoop:
    """周期性地:挑队首 pending 任务 → prober 空闲够就放行 → 等它真落地(或超时)才看下一个。"""

    def __init__(self, interval: float = 5.0, landed_timeout: float = 180.0) -> None:
        self.interval = interval
        self.landed_timeout = landed_timeout
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._inflight: Optional[tuple[str, str, float]] = None  # (namespace, name, admitted_ts)

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, name="queue-admission", daemon=True)
        self._thread.start()
        logger.info("AdmissionLoop 已启动(间隔=%ss,落地超时=%ss)", self.interval, self.landed_timeout)

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2.0)

    def _loop(self) -> None:
        while not self._stop.wait(self.interval):
            try:
                self.tick()
            except Exception as exc:  # noqa: BLE001 — 一次失败不该打断循环
                logger.warning("AdmissionLoop tick 失败: %s", exc)

    def tick(self) -> None:
        """跑一轮准入判断。拆成公开方法,单测直接调用、不用起线程等间隔。"""
        if self._inflight is not None:
            namespace, name, admitted_ts = self._inflight
            if _job_has_landed(namespace, name):
                logger.info("队列: %s/%s 已确认占卡,继续评估下一个候选", namespace, name)
                self._inflight = None
            elif time.time() - admitted_ts > self.landed_timeout:
                logger.warning(
                    "队列: %s/%s 放行 %.0fs 后仍未见占卡(可能拉镜像慢/启动失败),"
                    "超时兜底、继续评估下一个候选",
                    namespace, name, self.landed_timeout,
                )
                self._inflight = None
            else:
                return  # 还在等上一个落地,本轮不评估新的候选(核心原则 #2)

        jobs, err = list_queued_jobs()
        if err:
            return
        pending = order_pending([j for j in jobs if j.state == "pending"])
        if not pending:
            return

        head = pending[0]
        free = free_gpu_count(head.pool)
        if free is None or free < head.gpus:
            return  # 不知道 / 不够,都不放(核心原则 #1、#3)

        try:
            release_queued_job(head.namespace, head.name)
        except Exception as exc:  # noqa: BLE001
            logger.warning("队列自动放行 %s/%s 失败: %s", head.namespace, head.name, exc)
            return
        logger.info(
            "队列自动放行: %s/%s(池=%s 请求=%d卡 池内空闲=%d卡)",
            head.namespace, head.name, head.pool, head.gpus, free,
        )
        self._inflight = (head.namespace, head.name, time.time())
