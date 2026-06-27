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


def _read_nfs() -> tuple[str | None, str | None]:
    """读取集群级 NFS 配置(kube-system/gpuctl-config)。未配置 / 读不到 → (None, None)。"""
    try:
        from gpuctl.builder.base_builder import BaseBuilder
        cfg = BaseBuilder.read_nfs_config()
    except Exception:
        cfg = None
    return (cfg[0], cfg[1]) if cfg else (None, None)


def _view_context(request: Request, user: User, *, message: str | None = None, error: str | None = None) -> dict:
    settings = load_gpuctl_config()
    source = "incluster" if os.getenv("KUBERNETES_SERVICE_HOST") else "kubeconfig"
    effective_kubeconfig = settings.kubeconfig or os.getenv("KUBECONFIG") or "~/.kube/config"
    effective_context = settings.context or "<current-context>"
    nfs_server, nfs_path = _read_nfs()
    return {
        "user": user,
        "message": message,
        "error": error,
        "settings": settings,
        "config_path": get_config_path(),
        "source": source,
        "effective_kubeconfig": effective_kubeconfig,
        "effective_context": effective_context,
        "nfs_server": nfs_server,
        "nfs_path": nfs_path,
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


@router.post("/cluster-config/nfs")
async def cluster_config_nfs_post(
    request: Request,
    nfs_server: str = Form(...),
    nfs_path: str = Form(...),
    user: User = Depends(require_admin),
):
    """注册集群级 NFS 存储 —— 写 kube-system/gpuctl-config ConfigMap。

    复用 gpuctl 的 `init_storage`(与 `gpuctl init` 同一条路径,带校验、幂等)。
    成功后所有新建任务自动挂载 /home/jovyan + /datasets。
    """
    from gpuctl.cli.init import init_storage

    server = nfs_server.strip()
    path = nfs_path.strip()
    try:
        init_storage(server, path)
    except ValueError as exc:  # 参数非法(为空 / 路径不以 / 开头)
        return templates.TemplateResponse(
            request,
            "pages/cluster_config.html",
            _view_context(request, user, error=str(exc)),
            status_code=400,
        )
    except Exception as exc:  # K8s 连接 / 权限(如 SA 无 kube-system 写权限)等
        return templates.TemplateResponse(
            request,
            "pages/cluster_config.html",
            _view_context(request, user, error=f"写入 NFS 配置失败:{exc}"),
            status_code=400,
        )
    return RedirectResponse("/cluster-config?message=nfs-saved", status_code=302)

