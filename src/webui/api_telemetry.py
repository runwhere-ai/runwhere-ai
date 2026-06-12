"""任务遥测 REST API(/api/v1/telemetry,P0a)。

- POST:由 gpuctl 注入的遥测 sidecar 上报设备级 GPU 利用率(**免鉴权/免 CSRF**,
  因为 sidecar 不是浏览器、无会话;在集群内调用)。
- GET:供任务详情页轮询展示。

存储为内存滚动窗口(src/console/telemetry_store.py),无数据库。
设计见 docs/sidecar-agent-design.md。
"""
from __future__ import annotations

from fastapi import APIRouter, Response
from pydantic import BaseModel, Field

from src.console.telemetry_store import STORE


router = APIRouter(prefix="/api/v1/telemetry", tags=["telemetry"])


class TelemetrySample(BaseModel):
    namespace: str
    pod: str
    job_type: str = "unknown"
    gpu_index: int = 0
    gpu_util: float = 0.0
    mem_used: float = 0.0
    mem_total: float = 0.0


@router.post("", status_code=204)
async def ingest(sample: TelemetrySample) -> Response:
    STORE.ingest(
        namespace=sample.namespace, pod=sample.pod, job_type=sample.job_type,
        gpu_util=sample.gpu_util, mem_used=sample.mem_used, mem_total=sample.mem_total,
        gpu_index=sample.gpu_index,
    )
    return Response(status_code=204)


@router.get("/{namespace}/{pod}")
async def get_pod(namespace: str, pod: str) -> dict:
    data = STORE.get_pod(namespace, pod)
    if data is None:
        return {"namespace": namespace, "pod": pod, "has_data": False}
    data["has_data"] = True
    return data
