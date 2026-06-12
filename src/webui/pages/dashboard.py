"""Dashboard — live KPI summary sourced from gpuctl (jobs / pools / nodes)."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse

from src.console.models import User
from src.webui.deps import get_current_user
from src.webui.templating import templates


logger = logging.getLogger("src.webui.pages")
router = APIRouter(tags=["dashboard"])

_ZERO = {
    "running_jobs": 0, "total_jobs": 0,
    "gpu_total": 0, "gpu_used": 0, "util_pct": 0,
    "node_count": 0, "pool_count": 0,
    "gpu_util_pct": None, "gpu_mem_pct": None, "tele_n": 0,
}


async def _dashboard_stats(namespace: str | None = None) -> dict:
    """Aggregate live counts; degrade to zeros on any error (page must render).

    namespace=None → 全部;否则按全局选中的命名空间过滤(命名空间=用户)。
    """
    try:
        from server.routes.jobs import get_jobs
        from gpuctl.client.pool_client import PoolClient

        resp = await get_jobs(kind=None, pool=None, status=None, namespace=namespace, page=1, pageSize=200)
        jobs = resp.items
        running = sum(1 for j in jobs if j.status == "Running")

        client = PoolClient.get_instance()
        pools = client.list_pools()
        nodes = client.list_nodes()
        gpu_total = sum(p.get("gpu_total", 0) for p in pools)
        gpu_used = sum(p.get("gpu_used", 0) for p in pools)
        util = round(100 * gpu_used / gpu_total) if gpu_total else 0

        # 真实 GPU 利用率 / 显存占用率:聚合任务 sidecar 上报的【设备级】遥测
        # (见 src/console/telemetry_store.py)。仅计 fresh 上报;无上报则 None → 前端显 —。
        from src.console.telemetry_store import STORE
        tele = STORE.get_all()
        if namespace:
            tele = {k: v for k, v in tele.items() if k.split("/", 1)[0] == namespace}
        fresh = [d for d in tele.values() if d.get("fresh")]
        if fresh:
            gpu_util_pct = round(sum(d["gpu_util"] for d in fresh) / len(fresh))
            mems = [d["mem_used"] / d["mem_total"] * 100 for d in fresh if d.get("mem_total")]
            gpu_mem_pct = round(sum(mems) / len(mems)) if mems else None
        else:
            gpu_util_pct = gpu_mem_pct = None

        return {
            "running_jobs": running,
            "total_jobs": len(jobs),
            "gpu_total": gpu_total,
            "gpu_used": gpu_used,
            "util_pct": util,
            "node_count": len(nodes),
            "pool_count": len(pools),
            "gpu_util_pct": gpu_util_pct,
            "gpu_mem_pct": gpu_mem_pct,
            "tele_n": len(fresh),
        }
    except Exception as exc:  # noqa: BLE001 - dashboard must never 500
        logger.warning("dashboard stats failed: %s", exc)
        return dict(_ZERO)


@router.get("/")
async def root() -> RedirectResponse:
    return RedirectResponse("/dashboard", status_code=302)


@router.get("/dashboard")
async def dashboard(
    request: Request,
    user: User = Depends(get_current_user),
):
    from src.webui.pages.stubs import selected_namespace
    ns = selected_namespace(request)
    stats = await _dashboard_stats(ns)
    return templates.TemplateResponse(
        request,
        "pages/dashboard.html",
        {"user": user, "current_ns": ns, **stats},
    )
