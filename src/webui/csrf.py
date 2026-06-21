"""Double-submit CSRF token middleware (research R-02, F-02 fix).

For mutating requests (POST/PUT/PATCH/DELETE) the client must echo the
``csrf`` cookie value in the ``X-CSRF-Token`` header. We exclude:
  - safe methods (GET, HEAD, OPTIONS)
  - sessionless platform modes (kubeconfig / bypass)
  - the /login POST itself (no session yet)
  - the /logout POST (uses cookie evict, no body)
  - WS upgrade requests (auth checked at handshake)
"""
from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from src.config import CONFIG


_SAFE = {"GET", "HEAD", "OPTIONS"}
_BYPASS_PATHS = {"/login", "/logout"}


class CSRFMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next):
        if request.method in _SAFE:
            return await call_next(request)
        # Sessionless modes skip CSRF: there is no browser-held auth secret.
        if CONFIG.auth_provider in {"kubeconfig", "bypass"}:
            return await call_next(request)
        path = request.url.path
        if path in _BYPASS_PATHS or path.startswith("/_events") or path.startswith("/static"):
            return await call_next(request)
        # 遥测 ingest 由集群内 sidecar 调用(非浏览器、无会话密钥)→ 免 CSRF
        if path.startswith("/api/v1/telemetry"):
            return await call_next(request)
        # notebook 反向代理:jupyter 自带 XSRF 防护,透传即可 → 免 console CSRF
        if path.startswith("/nb/"):
            return await call_next(request)

        header_val = request.headers.get("X-CSRF-Token", "")
        cookie_val = request.cookies.get(CONFIG.csrf_cookie_name, "")
        if not header_val or not cookie_val or header_val != cookie_val:
            return JSONResponse(
                {"detail": "csrf_token_mismatch"},
                status_code=403,
            )
        return await call_next(request)
