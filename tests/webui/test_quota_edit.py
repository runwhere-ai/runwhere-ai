"""配额编辑/设置表单页(提交走 PUT /api/v1/quotas 幂等 upsert)。"""
from __future__ import annotations

from unittest.mock import patch

import pytest


@pytest.mark.asyncio
async def test_quota_page_no_quota_shows_set_cta(client):
    """无配额(无集群回退)时,页头给「设置配额」入口指向编辑表单。"""
    r = await client.get("/namespaces/team-x/quotas", headers={"Accept": "text/html"})

    assert r.status_code == 200
    assert 'href="/namespaces/team-x/quotas/edit"' in r.text
    assert "设置配额" in r.text


@pytest.mark.asyncio
async def test_quota_edit_action_is_inline_per_row(client):
    """有配额时,编辑入口在【行内操作列】(对应该命名空间),不在右上角页头。"""
    mock_quota = {
        "name": "team-x-quota", "namespace": "team-x",
        "hard": {"cpu": "4", "memory": "8Gi", "nvidia.com/gpu": "1"},
        "status": "Active",
    }
    with patch("gpuctl.client.quota_client.QuotaClient") as MockQC:
        MockQC.return_value.get_quota.return_value = mock_quota
        r = await client.get("/namespaces/team-x/quotas", headers={"Accept": "text/html"})

    assert r.status_code == 200
    assert "team-x-quota" in r.text
    # 新增「操作」列 + 行内「编辑配额」动作,指向该命名空间的编辑表单。
    assert "操作" in r.text
    assert "编辑配额" in r.text
    assert 'href="/namespaces/team-x/quotas/edit"' in r.text
    # 行内动作用的是表格 action 按钮样式(btn-outline),而非页头主 CTA(btn-primary)。
    assert "btn btn-outline" in r.text


@pytest.mark.asyncio
async def test_quota_edit_page_renders(client):
    r = await client.get("/namespaces/team-x/quotas/edit", headers={"Accept": "text/html"})

    assert r.status_code == 200
    assert "编辑配额" in r.text
    # 提交走 PUT /api/v1/quotas(与 CLI quota apply 同路径)。
    assert "/api/v1/quotas" in r.text
    assert "PUT" in r.text
    assert "team-x" in r.text


@pytest.mark.asyncio
async def test_quota_edit_default_namespace_uses_default_block(client):
    """default 命名空间的编辑页应走 default: 块(isDefault=true)。"""
    r = await client.get("/namespaces/default/quotas/edit", headers={"Accept": "text/html"})

    assert r.status_code == 200
    assert '"isDefault": true' in r.text
