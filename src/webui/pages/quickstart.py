"""快速开始(Quickstart)— 任务模板陈列馆 + 从模板启动 + 自定义模板编辑。

内置模板:src/console/templates_builtin.py(随代码发布,只读)。
自定义模板:本地文件存储,见 src/console/template_store.py(CRUD 经
/api/v1/templates,api_templates.py)。

提交复用 gpuctl 的 POST /api/v1/jobs,与 CLI 同一条代码路径;校验在本层
做"令牌替换占位值后的纯解析"(gpuctl 的 dryRun 字段当前被忽略 — design doc §8)。
"""
from __future__ import annotations

import secrets

import yaml as pyyaml
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, RedirectResponse

from src.console.models import User
from src.console.template_store import STORE, Template, validate_template_yaml, TemplateError
from src.webui.deps import get_current_user
from src.webui.templating import templates


router = APIRouter(tags=["quickstart"])

_KIND_LABEL = {"compute": "计算服务", "notebook": "Notebook",
               "inference": "推理服务", "training": "训练任务"}

# 与 stubs.py 的行图标风格一致(字符串字面量保留以便 Tailwind 扫描)
_KIND_ICON = {
    "notebook":  ("book-open", "bg-pink-100 text-pink-700 dark:bg-pink-900/30 dark:text-pink-400"),
    "training":  ("rocket",    "bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-400"),
    "inference": ("zap",       "bg-cyan-100 text-cyan-700 dark:bg-cyan-900/30 dark:text-cyan-400"),
    "compute":   ("cpu",       "bg-teal-100 text-teal-700 dark:bg-teal-900/30 dark:text-teal-400"),
}


def _card(t: Template) -> dict:
    icon_name, icon_cls = _KIND_ICON[t.kind]
    return {
        "name": t.name, "display": t.display, "description": t.description,
        "kind": t.kind, "kind_label": _KIND_LABEL[t.kind], "tags": t.tags,
        "builtin": t.builtin, "icon": icon_name, "icon_cls": icon_cls,
    }


@router.get("/quickstart")
async def quickstart(request: Request, kind: str | None = None,
                     user: User = Depends(get_current_user)):
    kinds = [("", "全部")] + [(k, _KIND_LABEL[k]) for k in ("notebook", "training", "inference", "compute")]
    items = [_card(t) for t in STORE.list_all(kind)]
    return templates.TemplateResponse(
        request, "pages/quickstart.html",
        {"user": user, "cards": items, "kinds": kinds, "active_kind": kind or ""},
    )


# 注意:/quickstart/new 必须注册在 /quickstart/{name} 之前
@router.get("/quickstart/new")
async def quickstart_new(request: Request, copy: str | None = None,
                         from_job: str | None = None, namespace: str = "default",
                         kind: str | None = None,
                         user: User = Depends(get_current_user)):
    """新建模板:空白 / 复制现有(copy=)/ 从任务另存(from_job=)。"""
    ctx = {"mode": "create", "name": "", "display": "", "description": "",
           "kind": kind if kind in _KIND_LABEL else "compute", "tags": "", "yaml": ""}

    if copy:
        t = STORE.get(copy)
        if t:
            ctx.update(name=f"{t.name}-copy", display=f"{t.display}(副本)",
                       description=t.description, kind=t.kind,
                       tags=",".join(t.tags), yaml=t.yaml)
    elif from_job:
        try:
            from server.routes.jobs import get_job_detail
            d = await get_job_detail(jobId=from_job, namespace=namespace)
            yc = d.yaml_content if isinstance(d.yaml_content, dict) else {}
            ctx.update(
                name=f"{from_job}-tpl"[:40],
                display=f"{from_job} 模板",
                description=f"从任务 {from_job} 另存",
                kind=d.kind if d.kind in _KIND_LABEL else "compute",
                yaml=pyyaml.safe_dump(yc, allow_unicode=True, sort_keys=False),
            )
        except Exception:
            pass  # 任务不存在时给空白表单
    elif ctx["kind"]:
        starter = next((t for t in STORE.list_all(ctx["kind"]) if t.builtin), None)
        if starter:
            ctx["yaml"] = starter.yaml

    return templates.TemplateResponse(
        request, "pages/template_edit.html",
        {"user": user, "kind_options": list(_KIND_LABEL.items()), **ctx},
    )


@router.get("/quickstart/{name}/edit")
async def quickstart_edit(name: str, request: Request,
                          user: User = Depends(get_current_user)):
    t = STORE.get(name)
    if not t:
        return RedirectResponse("/quickstart", status_code=302)
    if t.builtin:  # 内置只读 → 引导到复制流
        return RedirectResponse(f"/quickstart/new?copy={name}", status_code=302)
    return templates.TemplateResponse(
        request, "pages/template_edit.html",
        {"user": user, "mode": "edit", "name": t.name, "display": t.display,
         "description": t.description, "kind": t.kind, "tags": ",".join(t.tags),
         "yaml": t.yaml, "kind_options": list(_KIND_LABEL.items())},
    )


@router.get("/quickstart/{name}")
async def quickstart_launch(name: str, request: Request,
                            user: User = Depends(get_current_user)):
    t = STORE.get(name)
    if not t:
        return RedirectResponse("/quickstart", status_code=302)
    suggested = f"{t.name}-{secrets.token_hex(2)}"
    return templates.TemplateResponse(
        request, "pages/quickstart_launch.html",
        {
            "user": user, "tpl": _card(t), "tpl_yaml": t.yaml,
            "defaults": {
                "name": suggested, "namespace": "default", "pool": "default",
                "gpu": t.gpu, "cpu": t.cpu, "memory": t.memory, "image": t.image,
            },
        },
    )


@router.post("/quickstart/validate")
async def quickstart_validate(request: Request,
                              user: User = Depends(get_current_user)):
    """纯解析校验(令牌自动替换为占位值;不创建任何资源)。"""
    body = await request.json()
    try:
        kind = validate_template_yaml(body.get("yamlContent", ""))
        return JSONResponse({"ok": True, "kind": kind})
    except TemplateError as exc:
        return JSONResponse({"ok": False, "error": str(exc)})
