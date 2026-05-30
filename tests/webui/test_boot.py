"""Boot smoke tests: the app starts, /health works, auth gates protect /dashboard."""
from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_health_ok(client):
    r = await client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "version" in body


@pytest.mark.asyncio
async def test_meta_returns_provider(client):
    r = await client.get("/_meta")
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "runwhere-ai"
    assert body["auth_provider"] in {"bearer", "oidc"}


@pytest.mark.asyncio
async def test_unauthed_dashboard_redirects_to_login(client):
    # Browsers send Accept: text/html — middleware should redirect.
    r = await client.get("/dashboard", headers={"Accept": "text/html"},
                          follow_redirects=False)
    assert r.status_code in (302, 401)
    if r.status_code == 302:
        assert "/login" in r.headers.get("location", "")


@pytest.mark.asyncio
async def test_unauthed_htmx_dashboard_gets_hx_redirect(client):
    r = await client.get(
        "/dashboard",
        headers={"HX-Request": "true", "Accept": "text/html"},
        follow_redirects=False,
    )
    assert r.status_code == 401
    assert "/login" in r.headers.get("hx-redirect", "")


@pytest.mark.asyncio
async def test_root_redirects_to_dashboard(client):
    r = await client.get("/", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"] == "/dashboard"


@pytest.mark.asyncio
async def test_login_page_renders(client):
    r = await client.get("/login")
    assert r.status_code == 200
    assert "text/html" in r.headers.get("content-type", "")
    body = r.text
    # Title + form must be present
    assert "登录" in body
    assert "<form" in body
    assert 'name="token"' in body
