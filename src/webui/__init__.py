"""runwhere-ai UI routes (HTML + HTMX fragments + WebSocket).

This sub-package registers the *web* surface of runwhere-ai. It is mounted
on the same FastAPI app as gpuctl's `/api/v1/*` JSON routes (see
`src.main`), forming the **third interface** alongside CLI and REST
(constitution §II equivalence clause).
"""
from __future__ import annotations

from fastapi import FastAPI


def register_routes(app: FastAPI) -> None:
    """Mount all UI routers + middlewares + error handlers on ``app``."""
    # ── Middlewares (outer-most first) ───────────────────────────────────────
    from src.webui.middleware import RequestIdMiddleware
    from src.webui.csrf import CSRFMiddleware

    app.add_middleware(CSRFMiddleware)
    app.add_middleware(RequestIdMiddleware)

    # ── Global error handlers ────────────────────────────────────────────────
    from src.webui.errors import register_handlers
    register_handlers(app)

    # ── Routers ──────────────────────────────────────────────────────────────
    from src.webui.auth import router as auth_router
    from src.webui.ws_events import router as ws_events_router
    from src.webui.pages.dashboard import router as dashboard_router
    from src.webui.pages.cluster_config import router as cluster_config_router
    from src.webui.pages.quickstart import router as quickstart_router
    from src.webui.api_templates import router as api_templates_router
    from src.webui.pages.stubs import router as stubs_router

    app.include_router(api_templates_router)
    app.include_router(auth_router)
    app.include_router(ws_events_router)
    app.include_router(dashboard_router)
    app.include_router(cluster_config_router)
    app.include_router(quickstart_router)
    app.include_router(stubs_router)
