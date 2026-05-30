"""Dashboard placeholder — full implementation lives in US7 (Phase 8)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse

from src.console.models import User
from src.webui.deps import get_current_user
from src.webui.templating import templates


router = APIRouter(tags=["dashboard"])


@router.get("/")
async def root() -> RedirectResponse:
    return RedirectResponse("/dashboard", status_code=302)


@router.get("/dashboard")
async def dashboard(
    request: Request,
    user: User = Depends(get_current_user),
):
    return templates.TemplateResponse(
        request,
        "pages/dashboard.html",
        {"user": user},
    )
