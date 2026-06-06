"""Cluster configuration page backed by gpuctl config."""
from __future__ import annotations

import os

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse

from gpuctl.kube_config import clear_kubeconfig, get_config_path, load_gpuctl_config, save_kubeconfig
from src.console.models import User
from src.webui.deps import require_admin
from src.webui.templating import templates


router = APIRouter(tags=["cluster-config"])


def _view_context(request: Request, user: User, *, message: str | None = None, error: str | None = None) -> dict:
    settings = load_gpuctl_config()
    source = "incluster" if os.getenv("KUBERNETES_SERVICE_HOST") else "kubeconfig"
    effective_kubeconfig = settings.kubeconfig or os.getenv("KUBECONFIG") or "~/.kube/config"
    effective_context = settings.context or "<current-context>"
    return {
        "user": user,
        "message": message,
        "error": error,
        "settings": settings,
        "config_path": get_config_path(),
        "source": source,
        "effective_kubeconfig": effective_kubeconfig,
        "effective_context": effective_context,
    }


@router.get("/cluster-config")
async def cluster_config_get(
    request: Request,
    user: User = Depends(require_admin),
):
    return templates.TemplateResponse(
        request,
        "pages/cluster_config.html",
        _view_context(request, user),
    )


@router.post("/cluster-config")
async def cluster_config_post(
    request: Request,
    kubeconfig: str = Form(...),
    context: str = Form(""),
    user: User = Depends(require_admin),
):
    path = kubeconfig.strip()
    ctx = context.strip() or None
    if not path:
        return templates.TemplateResponse(
            request,
            "pages/cluster_config.html",
            _view_context(request, user, error="请输入服务端可访问的 kubeconfig 文件路径。"),
            status_code=400,
        )
    try:
        save_kubeconfig(path, ctx)
    except (FileNotFoundError, ValueError) as exc:
        return templates.TemplateResponse(
            request,
            "pages/cluster_config.html",
            _view_context(request, user, error=str(exc)),
            status_code=400,
        )
    return RedirectResponse("/cluster-config?message=saved", status_code=302)


@router.post("/cluster-config/clear")
async def cluster_config_clear(user: User = Depends(require_admin)):
    clear_kubeconfig()
    return RedirectResponse("/cluster-config?message=cleared", status_code=302)

