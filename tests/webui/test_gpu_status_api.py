"""GET /api/v1/gpu/status —— Agent 友好的结构化 GPU 状态(Agent-First PRD §4.2)。"""
from __future__ import annotations

import pytest

from src.console.gpu_prober import GpuProcess, PhysicalGpu


def _gpu(index=0, uuid="GPU-0", util=0.0, mem_used=0.0, mem_total=16311.0, processes=None):
    return PhysicalGpu(node="runw", index=index, uuid=uuid, name="RTX 5060 Ti",
                       util=util, mem_used_mb=mem_used, mem_total_mb=mem_total,
                       processes=processes or [])


class _FakeStore:
    def __init__(self, snapshot):
        self._snapshot = snapshot

    def snapshot(self):
        return self._snapshot


@pytest.mark.asyncio
async def test_gpu_status_empty_store_reports_unknown(client, monkeypatch):
    import src.webui.pages.gpu_overview as gpu_overview

    monkeypatch.setattr(gpu_overview, "STORE", _FakeStore({}))

    r = await client.get("/api/v1/gpu/status")

    assert r.status_code == 200
    body = r.json()
    assert body["nodes"] == []
    assert body["summary"] == {"total": 0, "free": 0, "busy": 0, "unmanaged": 0}
    assert body["unknown"] is True


@pytest.mark.asyncio
async def test_gpu_status_reflects_real_occupancy_not_k8s_allocation(client, monkeypatch):
    """三张卡:空闲、被 managed 进程占用、被非托管 docker 进程占用——三者状态都不同。"""
    import src.webui.pages.gpu_overview as gpu_overview

    managed_proc = GpuProcess(pid=1234, name="python", used_mem_mb=8000.0,
                              kind="managed", attrib="ft-qwen-001",
                              pod_namespace="leon", pod_name="ft-qwen-001")
    docker_proc = GpuProcess(pid=5678, name="vllm", used_mem_mb=4000.0,
                             kind="docker", attrib="docker abc123def456",
                             pod_namespace=None, pod_name=None)
    snapshot = {
        "runw": {"gpus": [
            _gpu(index=0, uuid="GPU-0"),
            _gpu(index=1, uuid="GPU-1", util=45.0, mem_used=8000.0, processes=[managed_proc]),
            _gpu(index=2, uuid="GPU-2", util=90.0, mem_used=4000.0, processes=[docker_proc]),
        ]},
    }
    monkeypatch.setattr(gpu_overview, "STORE", _FakeStore(snapshot))

    r = await client.get("/api/v1/gpu/status")

    assert r.status_code == 200
    body = r.json()
    assert body["unknown"] is False
    assert body["summary"] == {"total": 3, "free": 1, "busy": 1, "unmanaged": 1}

    gpus = body["nodes"][0]["gpus"]
    assert gpus[0]["status"] == "free"
    assert gpus[0]["processes"] == []

    assert gpus[1]["status"] == "busy"
    assert gpus[1]["utilization_pct"] == 45.0
    assert gpus[1]["memory_used_mb"] == 8000
    assert gpus[1]["processes"] == [{"pid": 1234, "name": "python", "user": "leon"}]

    assert gpus[2]["status"] == "unmanaged"
    # 非托管进程拿不到可靠的用户身份,宁可 None 不瞎猜(不是容器 id/进程名)
    assert gpus[2]["processes"] == [{"pid": 5678, "name": "vllm", "user": None}]


@pytest.mark.asyncio
async def test_gpu_status_requires_auth(client, monkeypatch):
    """未认证请求应该被拒绝,而不是悄悄放行(与其它 API 一致)。

    get_current_user 通过 FastAPI 的 Depends(get_auth_provider) 解析——那个 Depends
    在路由定义时就绑死了原函数对象,monkeypatch 模块属性 get_auth_provider 本身不生效；
    要改的是 get_auth_provider() 内部读取的缓存单例 _AUTH_PROVIDER。
    """
    import src.webui.pages.gpu_overview as gpu_overview
    from src.console.models import AuthError

    class _AlwaysDenies:
        async def authenticate(self, request):
            raise AuthError("no session")

    monkeypatch.setattr("src.webui.deps._AUTH_PROVIDER", _AlwaysDenies())
    monkeypatch.setattr(gpu_overview, "STORE", _FakeStore({}))

    r = await client.get("/api/v1/gpu/status")

    assert r.status_code == 401
