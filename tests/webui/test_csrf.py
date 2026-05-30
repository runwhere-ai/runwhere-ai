"""CSRF double-submit token middleware (research R-02 / F-02)."""
from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_safe_methods_bypass_csrf(client):
    r = await client.get("/health")
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_login_post_bypasses_csrf(client):
    # /login is in BYPASS_PATHS — no CSRF token required.
    r = await client.post("/login", data={"token": ""})
    # We don't care about token validity here, only that CSRF did not block.
    assert r.status_code in (200, 302, 400, 401)


@pytest.mark.asyncio
async def test_mismatched_csrf_token_rejected(client):
    # Hit a non-bypass POST without matching tokens.
    # /logout is in BYPASS, so use a fake protected path; the route will 404
    # *after* CSRF passes, or 403 *before*. We test the CSRF block.
    r = await client.post(
        "/dashboard",
        cookies={"csrf": "good"},
        headers={"X-CSRF-Token": "bad"},
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_matching_csrf_token_allowed_through(client):
    # Tokens match → CSRF middleware passes; downstream may still 401/405.
    r = await client.post(
        "/dashboard",
        cookies={"csrf": "samevalue"},
        headers={"X-CSRF-Token": "samevalue"},
    )
    # 405 (method not allowed) is fine — proves CSRF passed.
    assert r.status_code != 403
