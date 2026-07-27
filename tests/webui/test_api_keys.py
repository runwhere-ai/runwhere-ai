"""API Keys 管理页 + /api/v1 鉴权中间件在 console 里的接线（Agent-First PRD Phase 0）。"""
from __future__ import annotations

import pytest

from gpuctl.apikeys import ApiKeyStore
from server.routes.apikeys import set_store
from tests.webui.fake_apikey_k8s import FakeCoreV1


@pytest.fixture(autouse=True)
def fake_store():
    """所有测试共用一个内存 K8s 后端的 store，避免碰真实集群。"""
    store = ApiKeyStore(namespace="rw-system", core_v1=FakeCoreV1(), cache_ttl=30)
    set_store(store)
    yield store
    set_store(None)


@pytest.mark.asyncio
async def test_api_keys_page_renders_empty(client):
    r = await client.get("/api-keys", headers={"Accept": "text/html"})
    assert r.status_code == 200
    assert "API Keys" in r.text
    assert "还没有创建任何 API Key" in r.text


@pytest.mark.asyncio
async def test_create_key_shows_plaintext_once(client, fake_store):
    r = await client.post("/api-keys", data={
        "name": "claude-code-leon",
        "scopes": ["jobs:read", "jobs:write"],
        "bind_namespace": "leon",
        "expires_days": "",
    })
    assert r.status_code == 200
    assert "已创建「claude-code-leon」" in r.text
    assert "rw_" in r.text

    infos = fake_store.list()
    assert len(infos) == 1
    assert infos[0].name == "claude-code-leon"
    assert infos[0].namespace == "leon"


@pytest.mark.asyncio
async def test_create_key_rejects_no_scopes(client):
    r = await client.post("/api-keys", data={
        "name": "bad", "bind_namespace": "*", "expires_days": "",
    })
    assert r.status_code == 400
    assert "scope" in r.text


@pytest.mark.asyncio
async def test_revoke_key_removes_it(client, fake_store):
    _, info = fake_store.create("temp", ["jobs:read"])
    r = await client.post(f"/api-keys/{info.key_id}/revoke", follow_redirects=False)
    assert r.status_code == 302
    assert fake_store.list() == []


@pytest.mark.asyncio
async def test_json_api_key_management_routes_mounted(client, fake_store):
    """/api/v1/auth/api-keys 的 JSON 路由与 UI 共用同一个 store。"""
    r = await client.get("/api/v1/auth/api-keys")
    assert r.status_code == 200
    assert r.json() == []

    token, _ = fake_store.create("agent-x", ["gpu:read"])
    r = await client.get("/api/v1/auth/api-keys")
    assert len(r.json()) == 1


@pytest.mark.asyncio
async def test_default_auth_off_leaves_api_v1_open(client):
    """GPUCTL_API_AUTH 未设置(默认)时行为不变——不因本次改动引入回归。"""
    r = await client.get("/api/v1/pools")
    assert r.status_code != 401


async def _client_for_fresh_app():
    import httpx
    from src.main import create_app

    fresh_app = create_app()
    transport = httpx.ASGITransport(app=fresh_app)
    return httpx.AsyncClient(transport=transport, base_url="http://testserver")


@pytest.mark.asyncio
async def test_enforced_mode_browser_session_still_works_via_fallback(monkeypatch):
    """GPUCTL_API_AUTH=apikey 时，kubeconfig 模式的浏览器会话（无 Authorization 头）
    应继续通过 session fallback 过鉴权层，正常拿到数据（默认 auth_provider=kubeconfig 恒为 admin）。

    install_api_auth() 内部会自建一个 ApiKeyStore()；这里把 server.auth.ApiKeyStore
    换成一个预置 fake K8s 后端的工厂，让 create_app() 拿到的就是可控 store——
    不然真实 store 会在测试沙箱里因无集群而卡在 K8s 客户端的连接超时。
    """
    monkeypatch.setenv("GPUCTL_API_AUTH", "apikey")
    monkeypatch.setattr(
        "server.auth.ApiKeyStore",
        lambda *a, **k: ApiKeyStore(namespace="rw-system", core_v1=FakeCoreV1(), cache_ttl=30),
    )
    async with await _client_for_fresh_app() as c:
        r = await c.get("/api/v1/auth/api-keys")
    assert r.status_code == 200
    assert r.json() == []


class _AlwaysDeniesProvider:
    async def authenticate(self, request):
        from src.console.models import AuthError

        raise AuthError("no session")


@pytest.mark.asyncio
async def test_enforced_mode_rejects_missing_key_without_session(monkeypatch):
    """GPUCTL_API_AUTH=apikey + 无有效会话（如 bearer 模式无 cookie/token）→ 401 结构化错误。"""
    monkeypatch.setenv("GPUCTL_API_AUTH", "apikey")
    monkeypatch.setattr("src.webui.deps.get_auth_provider", lambda: _AlwaysDeniesProvider())
    async with await _client_for_fresh_app() as c:
        r = await c.get("/api/v1/pools")
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "UNAUTHENTICATED"


@pytest.mark.asyncio
async def test_agent_bearer_key_bypasses_csrf_for_mutation(client, fake_store, monkeypatch):
    """CSRF 中间件不该拦 Agent 的 Authorization: Bearer rw_... 调用（无浏览器 cookie 会话）。"""
    monkeypatch.setattr(
        "src.webui.csrf.CONFIG",
        type("C", (), {"auth_provider": "bearer", "csrf_cookie_name": "csrf"})(),
    )
    token, _ = fake_store.create("agent-y", ["jobs:write"])
    r = await client.post(
        "/api/v1/jobs",
        headers={"Authorization": f"Bearer {token}"},
        json={"kind": "training", "name": "x"},
    )
    # 405/422/500 都证明 CSRF 放行、请求打到了业务路由；只有 403 才代表被 CSRF 拦下。
    assert r.status_code != 403
