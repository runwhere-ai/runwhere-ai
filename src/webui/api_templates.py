"""任务模板 REST API(/api/v1/templates)。

先落 webui 层(design doc §7),稳定后下沉 gpuctl server/routes 并给 CLI 加
`gpuctl create --template <name>`。存储见 src/console/template_store.py。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from src.console.models import User
from src.console.template_store import STORE, Template, TemplateError
from src.webui.deps import get_current_user


router = APIRouter(prefix="/api/v1/templates", tags=["templates"])


class TemplateUpsert(BaseModel):
    display: str = ""
    description: str = ""
    kind: str
    tags: list[str] = Field(default_factory=list)
    yaml: str


def _item(t: Template, with_yaml: bool = False) -> dict:
    d = {
        "name": t.name, "display": t.display, "description": t.description,
        "kind": t.kind, "tags": list(t.tags), "builtin": t.builtin,
        "defaults": {"gpu": t.gpu, "cpu": t.cpu, "memory": t.memory, "image": t.image},
    }
    if with_yaml:
        d["yaml"] = t.yaml
    return d


@router.get("")
async def list_templates(kind: str | None = Query(None),
                         user: User = Depends(get_current_user)):
    items = STORE.list_all(kind)
    return {"total": len(items), "items": [_item(t) for t in items]}


@router.get("/{name}")
async def get_template(name: str, user: User = Depends(get_current_user)):
    t = STORE.get(name)
    if not t:
        raise HTTPException(status_code=404, detail=f"Template {name} not found")
    return _item(t, with_yaml=True)


class TemplateCreate(TemplateUpsert):
    name: str


@router.post("", status_code=201)
async def create_template(req: TemplateCreate,
                          user: User = Depends(get_current_user)):
    try:
        t = STORE.create(name=req.name, display=req.display, description=req.description,
                         kind=req.kind, tags=tuple(req.tags), yaml_text=req.yaml)
    except TemplateError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _item(t, with_yaml=True)


@router.put("/{name}")
async def update_template(name: str, req: TemplateUpsert,
                          user: User = Depends(get_current_user)):
    t0 = STORE.get(name)
    if not t0:
        raise HTTPException(status_code=404, detail=f"Template {name} not found")
    if t0.builtin:
        raise HTTPException(status_code=403, detail="内置模板只读,请使用「复制为新模板」")
    try:
        t = STORE.update(name=name, display=req.display, description=req.description,
                         kind=req.kind, tags=tuple(req.tags), yaml_text=req.yaml)
    except TemplateError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _item(t, with_yaml=True)


@router.delete("/{name}")
async def delete_template(name: str, user: User = Depends(get_current_user)):
    t0 = STORE.get(name)
    if not t0:
        raise HTTPException(status_code=404, detail=f"Template {name} not found")
    if t0.builtin:
        raise HTTPException(status_code=403, detail="内置模板只读,不能删除")
    try:
        STORE.delete(name)
    except TemplateError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"name": name, "deleted": True}
