"""Job list pages subscribe to /_events (WebSocket) for live status + row removal.

The shared /api/v1/jobs stays Pod-level; live updates are targeted OOB swaps pushed
over /_events — one channel (no tbody polling). Rows/status cells carry the OOB ids
(row-/status-{ns}-{kind}-{name}); admin lists (pools/namespaces) don't subscribe.
"""
from __future__ import annotations


async def test_job_list_subscribes_to_events_ws(client):
    r = await client.get("/trainings")
    assert r.status_code == 200
    assert 'hx-ext="ws"' in r.text
    assert 'ws-connect="/_events?ns=' in r.text
    assert "kind=training" in r.text


async def test_job_list_no_longer_polls(client):
    r = await client.get("/trainings")
    assert r.status_code == 200
    assert 'hx-trigger="every 5s"' not in r.text
    assert "?_rows=1" not in r.text


async def test_all_namespaces_uses_wildcard(client):
    # 测试环境无命名空间 cookie → 全部 → ws 用通配 *(urlencode 后 %2A)。
    r = await client.get("/trainings")
    assert r.status_code == 200
    assert ("ns=%2A" in r.text) or ("ns=*" in r.text)


async def test_admin_list_does_not_subscribe(client):
    r = await client.get("/pools")
    assert r.status_code == 200
    assert 'ws-connect="/_events' not in r.text
