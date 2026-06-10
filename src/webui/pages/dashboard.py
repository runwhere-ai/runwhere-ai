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
}


async def _dashboard_stats() -> dict:
    """Aggregate live counts; degrade to zeros on any error (page must render)."""
    try:
        from server.routes.jobs import get_jobs
        from gpuctl.client.pool_client import PoolClient

        resp = await get_jobs(kind=None, pool=None, status=None, namespace=None, page=1, pageSize=200)
        jobs = resp.items
        running = sum(1 for j in jobs if j.status == "Running")

        client = PoolClient.get_instance()
        pools = client.list_pools()
        nodes = client.list_nodes()
        gpu_total = sum(p.get("gpu_total", 0) for p in pools)
        gpu_used = sum(p.get("gpu_used", 0) for p in pools)
        util = round(100 * gpu_used / gpu_total) if gpu_total else 0

        return {
            "running_jobs": running,
            "total_jobs": len(jobs),
            "gpu_total": gpu_total,
            "gpu_used": gpu_used,
            "util_pct": util,
            "node_count": len(nodes),
            "pool_count": len(pools),
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
    stats = await _dashboard_stats()
    return templates.TemplateResponse(
        request,
        "pages/dashboard.html",
        {"user": user, **stats},
    )
