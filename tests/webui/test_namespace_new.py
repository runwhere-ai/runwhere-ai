"""新建命名空间表单页(通过「建配额即建命名空间」完成)。"""
from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_namespaces_cta_links_to_new_page(client):
    r = await client.get("/namespaces", headers={"Accept": "text/html"})

    assert r.status_code == 200
    # 「新建命名空间」按钮指向专门的表单页(不再是死链 ?new=1)。
    assert 'href="/namespaces/new"' in r.text
    assert 'href="/namespaces?new=1"' not in r.text


@pytest.mark.asyncio
async def test_namespace_new_page_renders_form(client):
    r = await client.get("/namespaces/new", headers={"Accept": "text/html"})

    assert r.status_code == 200
    assert "新建命名空间" in r.text
    # 提交走 gpuctl 的 quota 路由(建配额即建命名空间)。
    assert "/api/v1/quotas" in r.text
    # 表单字段:命名空间名 + 配额(CPU/内存/GPU)。
    assert "命名空间名" in r.text
    assert "资源配额" in r.text


@pytest.mark.asyncio
async def test_namespace_new_not_shadowed_by_quotas_param_route(client):
    """/namespaces/new 必须命中表单页,不能被 /namespaces/{namespace}/quotas 吞掉。"""
    r = await client.get("/namespaces/new", headers={"Accept": "text/html"})

    assert r.status_code == 200
    assert "· 配额" not in r.text  # 不是 quota 详情页
