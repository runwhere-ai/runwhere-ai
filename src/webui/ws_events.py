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
            html = _render_event(evt)
            await ws.send_text(html)
    except WebSocketDisconnect:
        pass
    except Exception as exc:  # pragma: no cover
        logger.warning("ws_events error: %s", exc)
    finally:
        hb_task.cancel()
        await bus.unsubscribe(handle)


async def _auth_ws(ws: WebSocket, auth: AuthProvider):
    # Build a tiny shim so AuthProvider.authenticate can read cookies.
    from src.config import CONFIG as _C
    cookie = ws.cookies.get(_C.session_cookie_name)
    if not cookie:
        raise AuthError("missing token")

    class _ShimRequest:
        cookies = {_C.session_cookie_name: cookie}
        headers = {}

    return await auth.authenticate(_ShimRequest())  # type: ignore[arg-type]


def _render_event(evt) -> str:
    """Render an InformerEvent into the OOB HTML fragment.

    For Phase 2 we emit the *minimum viable* fragments; later slices
    extend with per-kind row templates.
    """
    row_id = f"row-{evt.namespace}-{evt.kind.value}-{evt.name}"
    if evt.type == "DELETED":
        return (
            f'<tr id="{row_id}" hx-swap-oob="delete"></tr>'
        )
    # Generic placeholder row — pages/* slice templates will override.
    return (
        f'<tr id="{row_id}" hx-swap-oob="outerHTML" data-rv="{evt.resource_version}" '
        f'data-event="{evt.type}">'
        f'<td>{evt.name}</td><td>{evt.namespace}</td><td>{evt.kind.value}</td>'
        f'</tr>'
    )
