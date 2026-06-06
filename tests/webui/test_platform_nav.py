"""Platform navigation information architecture."""
from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_sidebar_collapses_nodes_and_quotas_into_parent_pages(client):
    r = await client.get("/dashboard", headers={"Accept": "text/html"})

    assert r.status_code == 200
    assert 'href="/pools"' in r.text
    assert "资源管理" in r.text
    assert 'href="/namespaces"' in r.text
    assert 'href="/nodes"' not in r.text
    assert 'href="/quotas"' not in r.text


@pytest.mark.asyncio
async def test_resource_management_links_to_pool_nodes(client):
    r = await client.get("/pools", headers={"Accept": "text/html"})

    assert r.status_code == 200
    assert "资源管理" in r.text
    assert 'href="/pools/pool-h100/nodes"' in r.text
    assert "gpu-h100-01" not in r.text


@pytest.mark.asyncio
async def test_pool_nodes_page_lists_nodes_for_selected_pool(client):
    r = await client.get("/pools/pool-h100/nodes", headers={"Accept": "text/html"})

    assert r.status_code == 200
    assert "pool-h100 · 节点" in r.text
    assert "gpu-h100-01" in r.text
    assert "gpu-a100-04" not in r.text


@pytest.mark.asyncio
async def test_namespaces_link_to_namespace_quotas(client):
    r = await client.get("/namespaces", headers={"Accept": "text/html"})

    assert r.status_code == 200
    assert "命名空间" in r.text
    assert 'href="/namespaces/team-llm/quotas"' in r.text
    assert "team-llm-quota" not in r.text


@pytest.mark.asyncio
async def test_namespace_quotas_page_lists_quotas_for_selected_namespace(client):
    r = await client.get("/namespaces/team-llm/quotas", headers={"Accept": "text/html"})

    assert r.status_code == 200
    assert "team-llm · 配额" in r.text
    assert "team-llm-quota" in r.text
    assert "team-vision-quota" not in r.text


@pytest.mark.asyncio
async def test_removed_menu_routes_redirect_to_parent_pages(client):
    nodes = await client.get("/nodes", follow_redirects=False)
    quotas = await client.get("/quotas", follow_redirects=False)

    assert nodes.status_code == 302
    assert nodes.headers["location"] == "/pools"
    assert quotas.status_code == 302
    assert quotas.headers["location"] == "/namespaces"
