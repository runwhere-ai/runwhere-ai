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


def _process_view(p) -> dict:
    # "user" 只在能可靠推出身份时给(managed → k8s namespace,本平台里 namespace = owner，
    # 见 job_queue.py 的 owner 语义);docker/host 进程拿不到真实用户，宁可 None 不猜。
    return {"pid": p.pid, "name": p.name, "user": p.pod_namespace if p.kind == "managed" else None}


def _gpu_status_view(g) -> dict:
    return {
        "index": g.index,
        "name": g.name,
        "uuid": g.uuid,
        "utilization_pct": round(g.util, 1),
        "memory_used_mb": round(g.mem_used_mb),
        "memory_total_mb": round(g.mem_total_mb),
        "processes": [_process_view(p) for p in g.processes],
        "status": g.state,  # "free" | "busy" | "unmanaged"
    }


@router.get("/api/v1/gpu/status")
async def gpu_status(user: User = Depends(get_current_user)):
    """Agent 友好的结构化 GPU 状态(Agent-First PRD §4.2)。

    数据源与 /gpu 页面、/api/gpu/free-cards 相同(gpu_prober.STORE 的真实占用)——
    这里只是换一层给 Agent 用的 JSON 形状(带 utilization/memory/processes 明细),
    不重新采集。STORE 无数据(未采集/无 GPU)时 summary 全 0、nodes 为空,不猜测。
    """
    snapshot = STORE.snapshot()
    nodes = []
    total = free = busy = unmanaged = 0
    for node, data in snapshot.items():
        gpus = data.get("gpus") or []
        nodes.append({"name": node, "gpus": [_gpu_status_view(g) for g in gpus]})
        for g in gpus:
            total += 1
            if g.state == "free":
                free += 1
            elif g.state == "unmanaged":
                unmanaged += 1
            else:
                busy += 1
    return JSONResponse({
        "nodes": nodes,
        "summary": {"total": total, "free": free, "busy": busy, "unmanaged": unmanaged},
        "unknown": not bool(snapshot),
    })


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
