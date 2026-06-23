"""Job list pages auto-refresh their tbody (htmx poll) so rows live-update.

Detail pages use a true WebSocket; lists use a periodic server re-render of the
grouped tbody (correct under pod-grouping). Admin lists (pools/namespaces) do not poll.
"""
from __future__ import annotations


async def test_job_list_full_page_wires_tbody_poll(client):
    r = await client.get("/trainings")
    assert r.status_code == 200
    assert 'hx-get="/trainings?_rows=1"' in r.text
    assert 'hx-trigger="every 5s"' in r.text


async def test_rows_fragment_returns_only_tbody(client):
    r = await client.get("/trainings?_rows=1")
    assert r.status_code == 200
    body = r.text
    assert "<tbody" in body
    # the polled-in fragment keeps polling itself
    assert 'hx-get="/trainings?_rows=1"' in body
    # it is a bare fragment, not a full page
    assert "<html" not in body.lower()
    assert "<head" not in body.lower()


async def test_admin_list_does_not_poll(client):
    r = await client.get("/pools")
    assert r.status_code == 200
    assert "?_rows=1" not in r.text
    assert 'hx-trigger="every 5s"' not in r.text
