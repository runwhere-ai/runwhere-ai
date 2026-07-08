"""GPU 大盘 —— 每张物理卡 → 任务 → 进程 的真实占用视图（设计 #2）。

数据来源:`src/console/gpu_prober.py` 的 RealityStore（prober hostPID + nvidia-smi 采集）。
- STORE 有数据（在 GPU 节点、prober 已采集）→ 渲染**真实**占用。
- STORE 无数据（本地无 GPU / prober 未启）→ 显示未知/未覆盖，不用样例数据冒充真实状态。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from src.console.gpu_prober import STORE
from src.console.models import User
from src.webui.deps import get_current_user
from src.webui.templating import templates

router = APIRouter(tags=["gpu-overview"])


@router.get("/api/gpu/free-cards")
async def free_cards(request: Request, user: User = Depends(get_current_user)):
    """供高级手动钉卡交互按需读取真实空闲卡。"""
    out = []
    snapshot = STORE.snapshot()
    for node, data in snapshot.items():
        for g in data.get("gpus") or []:
            if getattr(g, "state", "free") == "free":
                out.append({"node": node, "index": g.index, "uuid": g.uuid, "name": g.name})
    return JSONResponse({"cards": out, "unknown": not bool(snapshot)})


# ── RealityStore → 模板视图 ─────────────────────────────────────────────────────
def _proc_view(p) -> dict:
    mem_g = round(p.used_mem_mb / 1024.0, 1)
    mem_mb = int(round(p.used_mem_mb))
    if p.kind == "managed":
        return {"name": p.name, "pid": p.pid, "mem": mem_g, "mem_mb": mem_mb, "kind": "managed",
                "attrib": p.pod_name, "ns": p.pod_namespace, "image": None,
                "command": p.command or p.name}
    if p.kind == "docker":
        return {"name": p.name, "pid": p.pid, "mem": mem_g, "mem_mb": mem_mb, "kind": "docker",
                "attrib": (p.attrib or "").replace("docker ", ""), "image": None,
                "command": p.command or p.name}
    # host / unmanaged(k8s pod 未解析)：用 attrib 直接展示
    return {"name": p.name, "pid": p.pid, "mem": mem_g, "mem_mb": mem_mb, "kind": p.kind,
            "attrib": p.attrib, "ns": None, "image": None, "command": p.command or p.name}


def _occupant(g) -> str | None:
    if not g.processes:
        return None
    p = g.processes[0]
    return p.pod_name if p.kind == "managed" else (p.attrib or p.name)


def _card_view(g) -> dict:
    procs = sorted((_proc_view(p) for p in g.processes), key=lambda p: p["mem_mb"], reverse=True)
    return {
        "index": g.index, "uuid": g.uuid, "util": int(round(g.util)),
        "mem_used": round(g.mem_used_mb / 1024.0, 1),
        "mem_total": round(g.mem_total_mb / 1024.0, 1),
        "state": g.state, "occupant": _occupant(g),
        "procs": procs,
    }


def _store_to_view() -> dict:
    nodes = []
    for node, data in STORE.snapshot().items():
        gpus = data.get("gpus") or []
        cards = [_card_view(g) for g in gpus]
        nodes.append({
            "name": node,
            "gpu_model": gpus[0].name if gpus else "GPU",
            "reachable": True,
            "gpu_total": len(cards),
            "gpu_busy": sum(1 for c in cards if c["state"] != "free"),
            "gpu_unmanaged": sum(1 for c in cards if c["state"] == "unmanaged"),
            "cards": cards,
        })
    return {"nodes": nodes, "has_gpu_data": bool(nodes)}


@router.get("/gpu")
async def gpu_overview(request: Request, user: User = Depends(get_current_user)):
    data = _store_to_view()
    return templates.TemplateResponse(
        request, "pages/gpu_overview.html", {"user": user, **data}
    )
