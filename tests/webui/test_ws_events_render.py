"""Unit tests for _render_event: an InformerEvent → OOB HTML fragment(s).

MODIFIED/ADDED → live status badge(s) for the detail page (status-/status2- ids).
DELETED → list row delete + detail "deleted externally" banner. (contracts/ws-frames.md)
"""
from __future__ import annotations

import types

import pytest

from src.console.models import Kind


def _evt(typ, name="axolotl-ft", ns="default", kind=Kind.TRAINING, display_status="Running"):
    return types.SimpleNamespace(
        type=typ, namespace=ns, kind=kind, name=name,
        resource_version="100", object={"display_status": display_status},
    )


async def test_render_modified_emits_both_status_badges():
    from src.webui.ws_events import _render_event

    html = await _render_event(_evt("MODIFIED", display_status="Running"))
    assert 'id="status-default-training-axolotl-ft"' in html
    assert 'id="status2-default-training-axolotl-ft"' in html
    assert html.count('hx-swap-oob="outerHTML"') == 2
    assert "badge badge-" in html


async def test_render_modified_reflects_changed_status():
    from src.webui.ws_events import _render_event

    html = await _render_event(_evt("MODIFIED", display_status="OOMKilled"))
    # The badge must carry a tone class and a (Chinese) label — not the literal
    # "Unknown" fallback.
    assert "badge badge-" in html
    assert "Unknown" not in html


async def test_render_deleted_emits_banner_and_row_delete():
    from src.webui.ws_events import _render_event

    html = await _render_event(_evt("DELETED"))
    assert 'id="detail-deleted-banner"' in html
    assert 'id="row-default-training-axolotl-ft"' in html
    assert 'hx-swap-oob="delete"' in html


async def test_render_missing_object_falls_back_to_unknown():
    from src.webui.ws_events import _render_event

    evt = _evt("MODIFIED")
    evt.object = None
    html = await _render_event(evt)
    assert 'id="status-default-training-axolotl-ft"' in html


# ── _auth_ws: must not hard-require a cookie (console mode has none) ───────────

async def test_auth_ws_allows_console_mode_without_cookie():
    """KubeConfigProvider (default console mode) authenticates with no cookie —
    /_events must accept the connection, else realtime status never connects."""
    from src.webui.ws_events import _auth_ws
    from src.console.auth import KubeConfigProvider

    ws = types.SimpleNamespace(cookies={}, headers={})
    user = await _auth_ws(ws, KubeConfigProvider())
    assert user.subject == "system:runwhere-ai"


async def test_auth_ws_bearer_mode_still_rejects_without_token():
    """Bearer mode keeps enforcing its token inside authenticate()."""
    from src.webui.ws_events import _auth_ws
    from src.console.auth import BearerTokenProvider
    from src.console.models import AuthError

    ws = types.SimpleNamespace(cookies={}, headers={})
    with pytest.raises(AuthError):
        await _auth_ws(ws, BearerTokenProvider())
