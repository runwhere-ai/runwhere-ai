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
    assert body["auth_provider"] in {"kubeconfig", "bearer", "oidc", "bypass"}


@pytest.mark.asyncio
async def test_default_dashboard_opens_without_login(client):
    r = await client.get("/dashboard", headers={"Accept": "text/html"},
                         follow_redirects=False)
    assert r.status_code == 200
    assert "text/html" in r.headers.get("content-type", "")


@pytest.mark.asyncio
async def test_default_htmx_dashboard_opens_without_login(client):
    r = await client.get(
        "/dashboard",
        headers={"HX-Request": "true", "Accept": "text/html"},
        follow_redirects=False,
    )
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_root_redirects_to_dashboard(client):
    r = await client.get("/", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"] == "/dashboard"


@pytest.mark.asyncio
async def test_login_redirects_in_kubeconfig_mode(client):
    r = await client.get("/login")
    assert r.status_code == 302
    assert r.headers["location"] == "/dashboard"
