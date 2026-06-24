"""WebSocket endpoint /_events for real-time UI updates.

Frame protocol: contracts/ws-frames.md.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

from fastapi import APIRouter, Depends, Query, WebSocket
from fastapi.websockets import WebSocketState
from starlette.websockets import WebSocketDisconnect

from src.config import CONFIG
from src.console.auth import AuthProvider
from src.console.models import AuthError, Kind, Role
from src.console.pubsub import TopicBus
from src.webui.deps import get_auth_provider, get_pubsub


router = APIRouter()
logger = logging.getLogger(__name__)


@router.websocket("/_events")
async def events(
    ws: WebSocket,
    ns: str = Query(..., description="single namespace"),
    kind: list[str] = Query(..., description="one or more kinds"),
    auth: AuthProvider = Depends(get_auth_provider),
    bus: TopicBus = Depends(get_pubsub),
):
    """Subscribe to (ns, kind) topic set and stream HTML fragments."""
    # ── Authn / Authz at upgrade time ───────────────────────────────────────
    try:
        user = await _auth_ws(ws, auth)
    except AuthError:
        await ws.close(code=1008)
        return

    if Role.ADMIN not in user.roles and ns not in user.namespaces:
        await ws.close(code=1008)
        return

    # ── Parse + validate topic set ──────────────────────────────────────────
    try:
        kinds = [Kind(k) for k in kind]
    except ValueError:
        await ws.close(code=1003)
        return
    topics = {(ns, k) for k in kinds}
    if len(topics) > CONFIG.pubsub_max_topics_per_conn:
        await ws.close(code=1008)
        return

    await ws.accept()
    handle = await bus.subscribe(topics)

    async def heartbeat():
        try:
            while ws.client_state == WebSocketState.CONNECTED:
                await asyncio.sleep(CONFIG.ws_heartbeat_seconds)
                if ws.client_state == WebSocketState.CONNECTED:
                    await ws.send_text('<div id="hb" hx-swap-oob="true"></div>')
        except (WebSocketDisconnect, asyncio.CancelledError):
            return

    hb_task = asyncio.create_task(heartbeat())

    try:
        async for evt in bus.iterate(handle):
            html = await _render_event(evt)
            await ws.send_text(html)
    except WebSocketDisconnect:
        pass
    except Exception as exc:  # pragma: no cover
        logger.warning("ws_events error: %s", exc)
    finally:
        hb_task.cancel()
        await bus.unsubscribe(handle)


async def _auth_ws(ws: WebSocket, auth: AuthProvider):
    # Shim the WS's cookies + headers into a request-like object and let the
    # configured AuthProvider authenticate however it likes. We deliberately do NOT
    # hard-require a session cookie here: the default platform-console provider
    # (KubeConfigProvider) authenticates with a server-side K8s identity and no
    # browser cookie, so requiring one would wrongly reject EVERY /_events connection
    # in console mode (realtime status would silently never connect). Bearer mode
    # still enforces its token inside authenticate().
    class _ShimRequest:
        cookies = dict(ws.cookies)
        headers = ws.headers

    return await auth.authenticate(_ShimRequest())  # type: ignore[arg-type]


async def _render_event(evt) -> str:
    """Render an InformerEvent into OOB HTML fragment(s) (contracts/ws-frames.md).

    One event drives several pages, so we emit every fragment whose target *might*
    exist; htmx applies an `hx-swap-oob` only when its id is present on the page, so
    a list page picks up the `row-…` fragment, a detail page picks up the `status-…`
    badges / deletion banner, and unrelated pages ignore the rest.
    """
    ns, k, name = evt.namespace, evt.kind.value, evt.name
    row_id = f"row-{ns}-{k}-{name}"

    if evt.type == "DELETED":
        # List: drop the row. Detail: surface a "deleted externally" banner.
        # NOTE: the informer cache is keyed by (ns, controller-name) — one entry per
        # workload, last-pod-wins (see k8s_watch.normalize_pod + informer._handle_event).
        # So a DELETED faithfully means "this workload's representative pod is gone" and
        # removing the row is correct for the common single-pod case. A genuinely
        # multi-pod workload (distributed training parallelism>1) would need the cache
        # re-keyed by pod to avoid a transient row-drop — tracked as a follow-up.
        banner = (
            f'<div id="detail-deleted-banner" hx-swap-oob="outerHTML" '
            f'class="banner banner-warning">该对象已被删除（外部操作）。'
            f'<a href="/{k}s" class="underline">返回列表</a></div>'
        )
        return f'<tr id="{row_id}" hx-swap-oob="delete"></tr>{banner}'

    # ADDED / MODIFIED → live status badge for the detail page. Reuse the exact
    # badge logic the list/detail use (lazy import avoids a circular import).
    from src.webui.pages.stubs import status_badge

    status = (evt.object or {}).get("display_status") or "Unknown"
    sb = status_badge(status)
    cls = f'badge badge-{sb["tone"]} font-medium'   # 与列表/详情徽章类一致,OOB 替换不掉样式
    label = sb["badge"]
    # Two badges on the detail page (header + overview) → two distinct ids.
    return (
        f'<span id="status-{ns}-{k}-{name}" hx-swap-oob="outerHTML" class="{cls}">{label}</span>'
        f'<span id="status2-{ns}-{k}-{name}" hx-swap-oob="outerHTML" class="{cls}">{label}</span>'
    )
