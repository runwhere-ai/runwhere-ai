"""Double-submit CSRF token middleware (research R-02, F-02 fix).

For mutating requests (POST/PUT/PATCH/DELETE) the client must echo the
``csrf`` cookie value in the ``X-CSRF-Token`` header. We exclude:
  - safe methods (GET, HEAD, OPTIONS)
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
        # Dev bypass mode skips CSRF entirely — there's no real session anyway.
        if CONFIG.auth_provider == "bypass":
            return await call_next(request)
        path = request.url.path
        if path in _BYPASS_PATHS or path.startswith("/_events") or path.startswith("/static"):
            return await call_next(request)

        header_val = request.headers.get("X-CSRF-Token", "")
        cookie_val = request.cookies.get(CONFIG.csrf_cookie_name, "")
        if not header_val or not cookie_val or header_val != cookie_val:
            return JSONResponse(
                {"detail": "csrf_token_mismatch"},
                status_code=403,
            )
        return await call_next(request)
