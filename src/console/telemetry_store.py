"""任务遥测的内存滚动窗口(P0a)。

平台无数据库;遥测是 live 数据,丢失可接受(见 docs/sidecar-agent-design.md §4)。
按 namespace/pod 维度保存最近 N 个采样点 + last_seen,过期 pod 惰性清理。
sidecar(gpuctl 注入的 native sidecar)每隔几秒 POST 一个采样点过来。
"""
from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Dict, List, Optional, Tuple

# 每个 pod 保留的采样点数(5s 间隔 → ~5 分钟窗口)
_MAXLEN = 60
# 超过这个秒数没收到采样,视为过期,惰性清理
_TTL_SECONDS = 600


@dataclass
class Sample:
    ts: float
    gpu_util: float
    mem_used: float
    mem_total: float
    gpu_index: int = 0


@dataclass
class _Series:
    job_type: str = "unknown"
    last_seen: float = 0.0
    points: Deque[Sample] = field(default_factory=lambda: deque(maxlen=_MAXLEN))


class TelemetryStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._data: Dict[Tuple[str, str], _Series] = {}

    @staticmethod
    def _key(namespace: str, pod: str) -> Tuple[str, str]:
        return (namespace, pod)

    def ingest(self, namespace: str, pod: str, job_type: str,
               gpu_util: float, mem_used: float, mem_total: float,
               gpu_index: int = 0, ts: Optional[float] = None) -> None:
        now = ts if ts is not None else time.time()
        with self._lock:
            s = self._data.get(self._key(namespace, pod))
            if s is None:
                s = _Series(job_type=job_type)
                self._data[self._key(namespace, pod)] = s
            s.job_type = job_type or s.job_type
            s.last_seen = now
            s.points.append(Sample(now, gpu_util, mem_used, mem_total, gpu_index))

    def get_pod(self, namespace: str, pod: str) -> Optional[dict]:
        """返回某 pod 的最新值 + 序列;无数据返回 None。"""
        with self._lock:
            s = self._data.get(self._key(namespace, pod))
            if s is None or not s.points:
                return None
            latest = s.points[-1]
            series = [
                {"ts": round(p.ts, 1), "gpu_util": p.gpu_util,
                 "mem_used": p.mem_used, "mem_total": p.mem_total}
                for p in s.points
            ]
            return {
                "namespace": namespace, "pod": pod, "job_type": s.job_type,
                "last_seen": round(s.last_seen, 1), "fresh": (time.time() - s.last_seen) < 30,
                "latest": {
                    "gpu_util": latest.gpu_util, "mem_used": latest.mem_used,
                    "mem_total": latest.mem_total, "gpu_index": latest.gpu_index,
                },
                "series": series,
            }

    def get_all(self) -> dict:
        """所有 pod 的最新值(不含序列),供列表页一次性批量拉取。
        返回 {"<ns>/<pod>": {gpu_util, mem_used, mem_total, gpu_index, job_type, fresh}}。"""
        now = time.time()
        out: Dict[str, dict] = {}
        with self._lock:
            for (ns, pod), s in self._data.items():
                if not s.points:
                    continue
                latest = s.points[-1]
                out[f"{ns}/{pod}"] = {
                    "gpu_util": latest.gpu_util, "mem_used": latest.mem_used,
                    "mem_total": latest.mem_total, "gpu_index": latest.gpu_index,
                    "job_type": s.job_type, "fresh": (now - s.last_seen) < 30,
                }
        return out

    def prune(self) -> int:
        """清理过期 pod;返回清理数量。"""
        now = time.time()
        removed = 0
        with self._lock:
            for k in [k for k, s in self._data.items() if now - s.last_seen > _TTL_SECONDS]:
                del self._data[k]
                removed += 1
        return removed


STORE = TelemetryStore()
