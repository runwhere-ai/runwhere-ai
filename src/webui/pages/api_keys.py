"""API Keys 管理页（管理员）——签发 / 吊销供 Agent 调用 /api/v1 的 key。

Agent-First PRD §4.1 的 UI 落地：admin 在这里发一把 key 给某个 Agent
（如 claude-code-leon），Agent 之后用 ``Authorization: Bearer rw_...`` 调
/api/v1/*，鉴权由 gpuctl 的 ``ApiKeyAuthMiddleware`` 统一把关（见 src/main.py）。

复用 ``server.routes.apikeys`` 的同一个 store（而非各自 new 一份），保证
这里创建的 key 立刻能通过 JSON API 的鉴权中间件——两者共享同一份 K8s Secret
命名空间与同一份进程内校验缓存。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse

from gpuctl.apikeys import KNOWN_SCOPES
from server.routes.apikeys import get_store
from src.console.models import User
from src.webui.deps import require_admin
from src.webui.templating import templates

router = APIRouter(tags=["api-keys"])

# 管理页给一组常用 scope 预设，减少 Agent 接入时的勾选负担;"admin" 单列，需谨慎授予。
PRESET_SCOPES = sorted(s for s in KNOWN_SCOPES if s != "admin")


def _view_context(user: User, *, created_key: str | None = None,
                  created_name: str | None = None, error: str | None = None) -> dict:
    return {
        "user": user,
        "keys": get_store().list(),
        "preset_scopes": PRESET_SCOPES,
        "created_key": created_key,
        "created_name": created_name,
        "error": error,
    }


@router.get("/api-keys")
async def api_keys_get(request: Request, user: User = Depends(require_admin)):
    return templates.TemplateResponse(
        request, "pages/api_keys.html", _view_context(user),
    )


@router.post("/api-keys")
async def api_keys_create(
    request: Request,
    name: str = Form(...),
    scopes: list[str] = Form([]),
    bind_namespace: str = Form("*"),
    expires_days: str = Form(""),
    user: User = Depends(require_admin),
):
    days = int(expires_days) if expires_days.strip().isdigit() else None
    try:
        token, info = get_store().create(
            name=name, scopes=scopes,
            namespace=bind_namespace.strip() or "*",
            expires_days=days,
        )
    except ValueError as exc:
        return templates.TemplateResponse(
            request, "pages/api_keys.html",
            _view_context(user, error=str(exc)),
            status_code=400,
        )
    return templates.TemplateResponse(
        request, "pages/api_keys.html",
        _view_context(user, created_key=token, created_name=info.name),
    )


@router.post("/api-keys/{key_id}/revoke")
async def api_keys_revoke(key_id: str, user: User = Depends(require_admin)):
    get_store().revoke(key_id)
    return RedirectResponse("/api-keys", status_code=302)
