"""Global error handlers (spec FR-110, FR-111).

All non-2xx responses are routed through here so:
  - HTMX requests with 401 get ``HX-Redirect`` (auth-provider.md §5)
  - 403/404/412/428/5xx are rendered as styled error pages
  - server-side stack traces never leak to the client (FR-111)
"""
from __future__ import annotations

import logging
import uuid

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from src.console.consistency import ConsistencyGate
from src.console.models import (
    AuthError,
    ConflictError,
    ForbiddenError,
    PreconditionRequiredError,
)
from src.webui.templating import templates


logger = logging.getLogger(__name__)


def _is_htmx(request: Request) -> bool:
    return request.headers.get("HX-Request") == "true"


def _is_html(request: Request) -> bool:
    accept = request.headers.get("Accept", "")
    return "text/html" in accept


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", None) or str(uuid.uuid4())


def _render_error(request: Request, status: int, title: str, detail: str) -> HTMLResponse:
    rid = _request_id(request)
    body = templates.TemplateResponse(
        request,
        "pages/_error.html",
        {
            "status": status,
            "title": title,
            "detail": detail,
            "request_id": rid,
        },
        status_code=status,
    )
    body.headers["X-Request-Id"] = rid
    return body


def register_handlers(app: FastAPI) -> None:

    @app.exception_handler(HTTPException)
    async def http_handler(request: Request, exc: HTTPException):
        rid = _request_id(request)
        # 401 — HTMX clients should bounce to login transparently.
        if exc.status_code == 401:
            if _is_htmx(request):
                resp = JSONResponse({"detail": "not_authenticated"}, status_code=401)
                resp.headers["HX-Redirect"] = f"/login?next={request.url.path}"
                resp.headers["X-Request-Id"] = rid
                return resp
            if _is_html(request):
                return RedirectResponse(f"/login?next={request.url.path}", status_code=302)
            return JSONResponse({"detail": "not_authenticated"}, status_code=401,
                                headers={"X-Request-Id": rid})

        # All other HTML clients get a rendered page.
        if _is_html(request) and not _is_htmx(request):
            return _render_error(request, exc.status_code, _title_for(exc.status_code),
                                 str(exc.detail) if exc.detail else "")
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code,
                            headers={"X-Request-Id": rid})

    @app.exception_handler(AuthError)
    async def auth_err(request: Request, exc: AuthError):
        return await http_handler(request, HTTPException(status_code=401, detail=str(exc)))

    @app.exception_handler(ForbiddenError)
    async def forbidden(request: Request, exc: ForbiddenError):
        return await http_handler(request, HTTPException(status_code=403, detail=str(exc)))

    @app.exception_handler(PreconditionRequiredError)
    async def precondition_required(request: Request, exc: PreconditionRequiredError):
        return await http_handler(request, HTTPException(status_code=428, detail=str(exc)))

    @app.exception_handler(ConflictError)
    async def conflict(request: Request, exc: ConflictError):
        rid = _request_id(request)
        resp = await http_handler(request, HTTPException(status_code=412, detail=str(exc)))
        # Expose the current resourceVersion so the UI can refresh + merge.
        resp.headers["ETag"] = ConsistencyGate.format_etag(exc.current_resource_version)
        resp.headers["X-Request-Id"] = rid
        return resp

    @app.exception_handler(Exception)
    async def fallback(request: Request, exc: Exception):  # pragma: no cover - last resort
        rid = _request_id(request)
        logger.exception("unhandled exception (request_id=%s)", rid)
        if _is_html(request):
            return _render_error(request, 500, _title_for(500),
                                 "An unexpected error occurred. Please retry.")
        return JSONResponse({"detail": "internal_error"}, status_code=500,
                            headers={"X-Request-Id": rid})


def _title_for(status: int) -> str:
    return {
        400: "请求无效",
        401: "未登录",
        403: "无权访问",
        404: "未找到",
        412: "对象已被他人修改",
        428: "缺少 If-Match 头",
        500: "服务器内部错误",
    }.get(status, "出错了")
