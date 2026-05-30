"""Contract tests for the auth module (FR-001~004 + clarify Q1)."""
from __future__ import annotations

import pytest

from src.console.auth import (
    BearerTokenProvider,
    OidcProvider,
    _TokenCache,
    make_auth_provider,
)
from src.console.models import AuthError, Role, User


class TestTokenCache:
    @pytest.mark.asyncio
    async def test_put_get_round_trip(self):
        c = _TokenCache(ttl_seconds=60)
        user = User(subject="alice")
        await c.put("tok1", user)
        got = await c.get("tok1")
        assert got is not None
        assert got.subject == "alice"

    @pytest.mark.asyncio
    async def test_miss_returns_none(self):
        c = _TokenCache(ttl_seconds=60)
        assert await c.get("nope") is None

    @pytest.mark.asyncio
    async def test_ttl_expiry(self, monkeypatch):
        import src.console.auth as auth_mod
        c = _TokenCache(ttl_seconds=1)
        await c.put("k", User(subject="u"))
        # Fast-forward beyond TTL via time monkey-patch
        original = auth_mod.time.time
        monkeypatch.setattr(auth_mod.time, "time", lambda: original() + 10)
        assert await c.get("k") is None

    @pytest.mark.asyncio
    async def test_evict(self):
        c = _TokenCache(ttl_seconds=60)
        await c.put("k", User(subject="u"))
        await c.evict("k")
        assert await c.get("k") is None


class TestExtractToken:
    def test_from_cookie(self):
        p = BearerTokenProvider()

        class Req:
            cookies = {"rw_token": "abc"}
            headers = {}

        assert p._extract_token(Req()) == "abc"

    def test_from_authorization_header(self):
        p = BearerTokenProvider()

        class Req:
            cookies = {}
            headers = {"Authorization": "Bearer xyz"}

        assert p._extract_token(Req()) == "xyz"

    def test_cookie_takes_precedence(self):
        p = BearerTokenProvider()

        class Req:
            cookies = {"rw_token": "from-cookie"}
            headers = {"Authorization": "Bearer from-header"}

        assert p._extract_token(Req()) == "from-cookie"

    def test_neither_returns_none(self):
        p = BearerTokenProvider()

        class Req:
            cookies = {}
            headers = {}

        assert p._extract_token(Req()) is None

    def test_bare_bearer_returns_none(self):
        p = BearerTokenProvider()

        class Req:
            cookies = {}
            headers = {"Authorization": "Bearer "}

        assert p._extract_token(Req()) is None


class TestDeriveRoles:
    def test_system_masters_is_admin(self):
        roles = BearerTokenProvider._derive_roles("alice", ["system:masters"])
        assert Role.ADMIN in roles

    def test_runwhere_admin_group_is_admin(self):
        roles = BearerTokenProvider._derive_roles("alice", ["runwhere:admin"])
        assert Role.ADMIN in roles

    def test_plain_user_is_namespace_user(self):
        roles = BearerTokenProvider._derive_roles("alice", ["system:authenticated"])
        assert Role.NAMESPACE_USER in roles
        assert Role.ADMIN not in roles

    def test_empty_groups(self):
        roles = BearerTokenProvider._derive_roles("alice", [])
        assert roles == [Role.NAMESPACE_USER]


class TestAuthenticateNoToken:
    @pytest.mark.asyncio
    async def test_missing_token_raises_auth_error(self):
        p = BearerTokenProvider()

        class Req:
            cookies = {}
            headers = {}

        with pytest.raises(AuthError):
            await p.authenticate(Req())


class TestAuthenticateWithCache:
    @pytest.mark.asyncio
    async def test_cached_user_skips_k8s_call(self):
        p = BearerTokenProvider()
        cached_user = User(subject="cached", roles=[Role.NAMESPACE_USER])
        await p._cache.put("cached-tok", cached_user)

        class Req:
            cookies = {"rw_token": "cached-tok"}
            headers = {}

        got = await p.authenticate(Req())
        assert got.subject == "cached"


class TestOidcStub:
    """Stubs MUST raise — they're contract placeholders, not implementations."""

    @pytest.mark.asyncio
    async def test_authenticate_raises_notimplemented(self):
        with pytest.raises(NotImplementedError):
            await OidcProvider().authenticate(None)  # type: ignore[arg-type]

    @pytest.mark.asyncio
    async def test_begin_login_raises(self):
        with pytest.raises(NotImplementedError):
            await OidcProvider().begin_login(None)  # type: ignore[arg-type]

    def test_login_url(self):
        assert OidcProvider().login_url == "/oidc/start"


class TestFactory:
    def test_default_is_bearer(self, monkeypatch):
        monkeypatch.setattr("src.console.auth.CONFIG",
                            type("C", (), {"auth_provider": "bearer", "token_review_cache_seconds": 60})())
        p = make_auth_provider()
        assert isinstance(p, BearerTokenProvider)

    def test_oidc_when_configured(self, monkeypatch):
        monkeypatch.setattr("src.console.auth.CONFIG",
                            type("C", (), {"auth_provider": "oidc", "token_review_cache_seconds": 60})())
        p = make_auth_provider()
        assert isinstance(p, OidcProvider)
