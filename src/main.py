"""FastAPI application entrypoint for runwhere-ai.

Mounts BOTH gpuctl's existing `/api/v1/*` JSON routes AND the new
HTML / HTMX UI routes in the same process (spec FR-116). The browser
talks only to this process; K8s API is reached exclusively from the
server-side Service layer (spec FR-115).
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
import os

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from src import __version__
from src.config import CONFIG
from gpuctl.kube_config import load_gpuctl_config

logger = logging.getLogger("src")
logging.basicConfig(
    level=getattr(logging, CONFIG.log_level.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

# Repository-root anchor for static/templates lookup.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent


async def _start_informer_safe(inf) -> None:
    """Start one informer, swallowing failures (e.g. no cluster in dev/test).

    A failed start just means realtime status is disabled for that kind — the UI
    still works (pages render on request); it must never break app boot.
    """
    try:
        await inf.start()
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "SharedInformer[%s] failed to start; realtime status disabled for this kind: %s",
            getattr(inf, "kind", "?"), exc,
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown wiring: start one SharedInformer per Kind so job status
    streams to the browser over /_events (spec FR-100/101). Pubsub is the shared
    singleton bus the WS endpoint subscribes to.

    Startup is deliberately resilient: if there is no reachable cluster (local dev,
    unit tests), informers just don't start and the app boots normally.
    """
    logger.info("runwhere-ai %s starting…", __version__)
    informers: list = []
    try:
        from src.console.informer import SharedInformer
        from src.console.k8s_watch import make_pod_adapter
        from src.console.models import Kind
        from src.console.pubsub import get_topic_bus

        bus = get_topic_bus()
        for kind in Kind:
            list_fn, watch_fn = make_pod_adapter(kind)
            informers.append(
                SharedInformer(kind, list_fn=list_fn, watch_fn=watch_fn, topic_bus=bus)
            )
        # Start in the background so a slow/absent cluster never blocks boot.
        for inf in informers:
            asyncio.create_task(_start_informer_safe(inf))
        app.state.informers = informers
        logger.info("started %d SharedInformer(s) for realtime status", len(informers))
    except Exception as exc:  # noqa: BLE001
        logger.warning("informers not started; realtime status disabled: %s", exc)

    # GPU prober（form A：进程内，hostPID）—— 采集本节点整卡占用 → RealityStore → GPU 大盘。
    # 需容器具备 hostPID + nvidia runtime；无 GPU（本地/无卡）则 start() 自动空转，不影响启动。
    app.state.gpu_prober = None
    try:
        import os
        import socket

        from src.console.gpu_prober import GpuProber, make_k8s_pod_resolver

        node = os.getenv("NODE_NAME") or socket.gethostname()
        prober = GpuProber(node=node, resolver=make_k8s_pod_resolver())
        await asyncio.get_running_loop().run_in_executor(None, prober.start)
        app.state.gpu_prober = prober
    except Exception as exc:  # noqa: BLE001
        logger.warning("GpuProber 未启动: %s", exc)

    # 队列自动准入（停车场 -> 真队列）：定时检查 prober 真实空闲卡数，够就放行队首。
    # 依赖上面的 gpu_prober（判定空闲的唯一数据源）；无 prober 数据时循环只是安全地什么都不做。
    app.state.queue_admission = None
    if CONFIG.queue_auto_admit:
        try:
            from src.console.queue_admission import AdmissionLoop

            admission = AdmissionLoop(
                interval=CONFIG.queue_admission_interval_seconds,
                landed_timeout=CONFIG.queue_admission_landed_timeout_seconds,
            )
            admission.start()
            app.state.queue_admission = admission
        except Exception as exc:  # noqa: BLE001
            logger.warning("AdmissionLoop 未启动: %s", exc)

    yield

    if getattr(app.state, "queue_admission", None):
        try:
            app.state.queue_admission.stop()
        except Exception:  # noqa: BLE001
            pass
    for inf in informers:
        try:
            await inf.stop()
        except Exception:  # noqa: BLE001
            pass
    if getattr(app.state, "gpu_prober", None):
        try:
            app.state.gpu_prober.stop()
        except Exception:  # noqa: BLE001
            pass
    logger.info("runwhere-ai shutting down…")


def create_app() -> FastAPI:
    """Application factory — used both by uvicorn and by tests."""
    app = FastAPI(
        title="runwhere-ai",
        description="一体化 Web 控制台：Notebook · Training · Inference · Compute",
        version=__version__,
        lifespan=lifespan,
    )

    # ── Mount static assets ──────────────────────────────────────────────────
    static_dir = _PROJECT_ROOT / CONFIG.static_dir
    if static_dir.is_dir():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
    else:
        logger.warning("static dir %s does not exist; /static will 404", static_dir)

    # ── Mount gpuctl's existing /api/v1/* routers ───────────────────────────
    # These are reused verbatim (CLI ↔ UI single source of truth, spec FR-117).
    try:
        from server.routes import (  # type: ignore
            jobs_router,
            pools_router,
            nodes_router,
            labels_router,
            global_labels_router,
            quotas_router,
            namespaces_router,
        )

        app.include_router(jobs_router)
        app.include_router(pools_router)
        app.include_router(labels_router)
        app.include_router(nodes_router)
        app.include_router(quotas_router)
        app.include_router(namespaces_router)
        app.include_router(global_labels_router)
        logger.info("gpuctl /api/v1/* routers mounted")
    except Exception as exc:  # pragma: no cover - boot-time wiring
        logger.warning("gpuctl routers not mounted (%s); /api/v1/* will be absent.", exc)

    # ── Mount runwhere-ai UI routes (Phase 2 will populate) ──────────────────
    try:
        from src.webui import register_routes

        register_routes(app)
        logger.info("runwhere-ai UI routes mounted")
    except ImportError:
        logger.info("src.webui not yet wired; UI routes deferred to Phase 2.")

    # ── Health & meta ────────────────────────────────────────────────────────
    @app.get("/health")
    async def health() -> JSONResponse:
        return JSONResponse({"status": "ok", "version": __version__})

    @app.get("/_meta")
    async def meta() -> JSONResponse:
        gpuctl_config = load_gpuctl_config()
        return JSONResponse(
            {
                "name": "runwhere-ai",
                "version": __version__,
                "auth_provider": CONFIG.auth_provider,
                "k8s_config_source": "incluster" if os.getenv("KUBERNETES_SERVICE_HOST") else "kubeconfig",
                "kubeconfig": gpuctl_config.kubeconfig or os.getenv("KUBECONFIG") or None,
                "kube_context": gpuctl_config.context,
            }
        )

    return app


app = create_app()


def run() -> None:
    """`runwhere-ai` CLI entrypoint — wraps uvicorn for `poetry run runwhere-ai`."""
    import uvicorn

    uvicorn.run(
        "src.main:app",
        host=CONFIG.host,
        port=CONFIG.port,
        reload=True,
        log_level=CONFIG.log_level.lower(),
    )


if __name__ == "__main__":
    run()
