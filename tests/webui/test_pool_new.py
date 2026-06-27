"""新建资源池表单页 (/pools/new)。

资源池 = 一组打了 runwhere.ai/pool 标签的节点(gpuctl 无独立池对象),故表单要选节点。
GET 渲染:把节点列表经 tojson 注入选择器 + 现有池名(撞名提示);提交走与 CLI apply 相同的
结构化端点 POST /api/v1/pools。这里 mock 掉 PoolClient(无需 live cluster)。
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


def _fake_pool_client() -> MagicMock:
    inst = MagicMock()
    inst.list_nodes.return_value = [
        {
            "name": "gpu-node-01",
            "status": "active",
            "resources": {"gpu_total": 8, "gpu_used": 2, "gpu_free": 6},
            "gpu_types": ["a100-80g"],
            "labels": {"runwhere.ai/pool": "default"},
            "ip": "10.0.0.1",
        },
    ]
    inst.list_pools.return_value = [{"name": "pool-h100"}]
    return inst


@pytest.mark.asyncio
async def test_pools_cta_points_to_new_form(client):
    with patch("gpuctl.client.pool_client.PoolClient.get_instance", return_value=_fake_pool_client()):
        r = await client.get("/pools", headers={"Accept": "text/html"})
    assert r.status_code == 200
    assert 'href="/pools/new"' in r.text


@pytest.mark.asyncio
async def test_pool_new_renders_form_with_nodes(client):
    with patch("gpuctl.client.pool_client.PoolClient.get_instance", return_value=_fake_pool_client()):
        r = await client.get("/pools/new", headers={"Accept": "text/html"})
    assert r.status_code == 200
    assert "新建资源池" in r.text
    # 提交走与 CLI apply 相同的结构化端点
    assert "/api/v1/pools" in r.text
    # 节点经 tojson 注入选择器(供 Alpine 渲染复选行)
    assert "gpu-node-01" in r.text
    assert "a100-80g" in r.text
    # 现有池名注入,用于「该池已存在」撞名提示
    assert "pool-h100" in r.text


@pytest.mark.asyncio
async def test_pools_list_has_delete_button_except_default(client):
    """池列表「操作」列:非 default 池有删除按钮(rwDeletePool),default 池不可删(占位)。"""
    inst = MagicMock()
    inst.list_pools.return_value = [
        {"name": "default", "status": "active", "gpu_total": 4, "gpu_used": 2, "gpu_free": 2, "nodes": ["runw"]},
        {"name": "a100-train", "status": "active", "gpu_total": 8, "gpu_used": 0, "gpu_free": 8, "nodes": ["n1"]},
    ]
    with patch("gpuctl.client.pool_client.PoolClient.get_instance", return_value=inst):
        r = await client.get("/pools", headers={"Accept": "text/html"})
    assert r.status_code == 200
    assert "操作" in r.text
    assert "rwDeletePool('a100-train',this)" in r.text
    # default 是隐式兜底池,不给删除按钮
    assert "rwDeletePool('default'" not in r.text


@pytest.mark.asyncio
async def test_pool_new_renders_empty_state_off_cluster(client):
    """取不到节点(集群不可达)也照常 200 渲染空态,不 500 整页。"""
    failing = MagicMock()
    failing.list_nodes.side_effect = RuntimeError("no cluster")
    with patch("gpuctl.client.pool_client.PoolClient.get_instance", return_value=failing):
        r = await client.get("/pools/new", headers={"Accept": "text/html"})
    assert r.status_code == 200
    assert "新建资源池" in r.text
