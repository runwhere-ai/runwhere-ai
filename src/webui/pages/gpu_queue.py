"""任务队列(看自己排第几)—— 设计 #3「提交就睡」的队列视图。

数据来源:K8s Job 对象上的 `runwhere.ai/queued=true` 标签。这里只是视图 + 手动放行
入口;自动准入的判断逻辑在 `src.console.queue_admission.AdmissionLoop`(随 app
lifespan 启停,见 `src/main.py`),复用的正是本模块下面 import 的
list_queued_jobs / order_pending / release_queued_job。
"""
from __future__ import annotations

from datetime import datetime, timezone
import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from src.console.job_queue import (
    QueuedJob,
    list_queued_jobs,
    order_pending,
    release_queued_job,
)
from src.console.models import User
from src.webui.deps import get_current_user
from src.webui.templating import templates

router = APIRouter(tags=["gpu-queue"])
logger = logging.getLogger("src.webui.pages.gpu_queue")


def _waited(submitted_at: str, running: bool) -> str:
    try:
        ts = datetime.fromisoformat((submitted_at or "").replace("Z", "+00:00"))
        secs = (datetime.now(timezone.utc) - ts).total_seconds()
    except (ValueError, TypeError):
        return "—"
    if secs < 0:
        secs = 0
    if secs < 3600:
        human = f"{int(secs // 60)} 分钟"
    else:
        human = f"{secs / 3600:.1f} 小时"
    return f"已运行 {human}" if running else human


def _row(j, pos, state) -> dict:
    if state == "unschedulable":
        reason = f"要 {j.gpus} 卡，超过 {j.pool} 池上限 — 改请求或换池"
    elif state == "pending":
        reason = "排队中（等空闲卡）"
    else:
        reason = None
    return {
        "pos": pos, "namespace": j.namespace, "name": j.name,
        "owner": j.owner, "priority": j.priority,
        "gpus": j.gpus, "pool": j.pool, "waited": _waited(j.submitted_at, state == "running"),
        "state": state, "reason": reason, "cards": None,
    }


def _queue_to_view(jobs: list[QueuedJob]) -> dict:
    pending = order_pending([j for j in jobs if j.state == "pending"])
    running = [j for j in jobs if j.state in ("admitted", "running")]
    unsched = [j for j in jobs if j.state == "unschedulable"]
    rows = (
        [_row(j, i, "pending") for i, j in enumerate(pending, 1)]
        + [_row(j, None, "running") for j in running]
        + [_row(j, None, "unschedulable") for j in unsched]
    )
    return {"rows": rows, "pending_n": len(pending), "running_n": len(running)}


def queued_counts() -> tuple[int, int, bool]:
    """Return (pending, unschedulable, available) for dashboard summary."""
    jobs, err = list_queued_jobs()
    if err:
        return 0, 0, False
    pending = sum(1 for j in jobs if j.state == "pending")
    unsched = sum(1 for j in jobs if j.state == "unschedulable")
    return pending, unsched, True


@router.get("/queue")
async def gpu_queue(request: Request, user: User = Depends(get_current_user)):
    jobs, err = list_queued_jobs()
    data = _queue_to_view(jobs)
    return templates.TemplateResponse(
        request, "pages/gpu_queue.html",
        {"user": user, **data, "queue_error": err, "queue_available": err is None}
    )


@router.post("/queue/{namespace}/{name}/release")
async def release_queue_job(namespace: str, name: str,
                            user: User = Depends(get_current_user)):
    try:
        release_queued_job(namespace, name)
        return JSONResponse({"ok": True})
    except Exception as exc:  # noqa: BLE001
        logger.warning("release queued job %s/%s failed: %s", namespace, name, exc)
        return JSONResponse({"ok": False, "detail": str(exc)}, status_code=500)
