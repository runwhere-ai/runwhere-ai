"""AuthProvider abstraction + v1 BearerTokenProvider.

Spec FR-001, FR-002, FR-003, FR-004 + clarify Q1.

v1 ships BearerTokenProvider only. OidcProvider is a stub that raises
NotImplementedError to lock the extension point — the surface stays
stable so wiring the OIDC implementation in v2 won't disturb call sites.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional, Protocol, runtime_checkable

from fastapi import Request, Response
from fastapi.responses import RedirectResponse

from src.config import CONFIG
from src.console.models import AuthError, Role, User


logger = logging.getLogger(__name__)


# ─── Provider Protocol ────────────────────────────────────────────────────────

@runtime_checkable
class AuthProvider(Protocol):
    """All authentication flows go through this surface."""

    kind: str

    @property
    def login_url(self) -> str: ...

    async def authenticate(self, request: Request) -> User: ...

    async def begin_login(self, request: Request) -> Response: ...

    async def complete_login(self, request: Request) -> Response: ...

    async def logout(self, request: Request) -> Response: ...


# ─── v1 · Bearer Token ────────────────────────────────────────────────────────

class _TokenCache:
    """Tiny in-memory token-review cache.

    Reduces K8s API pressure: re-validate at most every
    ``CONFIG.token_review_cache_seconds`` per (token-hash, namespace).
    """

    def __init__(self, ttl_seconds: int) -> None:
        self._ttl = ttl_seconds
        self._store: dict[str, tuple[float, User]] = {}
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> Optional[User]:
        async with self._lock:
            entry = self._store.get(key)
        if entry is None:
            return None
        ts, user = entry
        if time.time() - ts > self._ttl:
            async with self._lock:
                self._store.pop(key, None)
            return None
        return user

    async def put(self, key: str, user: User) -> None:
        async with self._lock:
            self._store[key] = (time.time(), user)

    async def evict(self, key: str) -> None:
        async with self._lock:
            self._store.pop(key, None)


class BearerTokenProvider:
    """Authenticates via a Kubernetes Bearer token.

    Token sources (in order):
      1. Cookie ``CONFIG.session_cookie_name`` (HttpOnly, set by /login POST)
      2. ``Authorization: Bearer <token>`` header (programmatic / API)

    Resolution flow:
      - If neither source provides a token → AuthError
      - Look up cached User
      - On miss, call K8s TokenReview to validate + extract identity
      - Cache for ``CONFIG.token_review_cache_seconds``
    """

    kind = "bearer"

    def __init__(self) -> None:
        self._cache = _TokenCache(CONFIG.token_review_cache_seconds)

    @property
    def login_url(self) -> str:
        return "/login"

    # ── core: authenticate ──────────────────────────────────────────────────

    def _extract_token(self, request: Request) -> Optional[str]:
        cookie = request.cookies.get(CONFIG.session_cookie_name)
        if cookie:
            return cookie
        header = request.headers.get("Authorization", "")
        if header.startswith("Bearer "):
            return header[len("Bearer ") :].strip() or None
        return None

    async def authenticate(self, request: Request) -> User:
        token = self._extract_token(request)
        if not token:
            raise AuthError("missing token")
        cached = await self._cache.get(token)
        if cached is not None:
            return cached
        user = await self._whoami(token)
        await self._cache.put(token, user)
        return user

    async def _whoami(self, token: str) -> User:
        """Validate token + populate User.

        Calls K8s ``SelfSubjectReview`` (preferred) or ``TokenReview`` via
        kubernetes-asyncio. The actual K8s call is wired here but kept
        lazy-imported so unit tests can monkey-patch easily.
        """
        # Import locally so test code can stub kubernetes_asyncio without
        # making it a hard runtime prerequisite at module load.
        try:
            from kubernetes_asyncio import client, config as k8s_config  # type: ignore
        except Exception as exc:  # pragma: no cover - environment-dependent
            raise AuthError(f"kubernetes_asyncio not available: {exc}") from exc

        try:
            try:
                k8s_config.load_incluster_config()
            except Exception:
                await k8s_config.load_kube_config()
        except Exception as exc:
            raise AuthError(f"k8s config not loadable: {exc}") from exc

        api = client.AuthenticationV1Api()
        body = client.V1TokenReview(spec=client.V1TokenReviewSpec(token=token))
        try:
            review = await api.create_token_review(body=body)
        except Exception as exc:
            raise AuthError(f"token review failed: {exc}") from exc

        if not review.status or not review.status.authenticated:
            raise AuthError("token rejected by API server")

        username = review.status.user.username or "unknown"
        groups = list(review.status.user.groups or [])
        namespaces = await self._discover_namespaces(token, username)
        roles = self._derive_roles(username, groups)

        return User(
            subject=username,
            display_name=username.split(":")[-1] if ":" in username else username,
            namespaces=namespaces,
            roles=roles,
            token=token,
        )

    async def _discover_namespaces(self, token: str, username: str) -> list[str]:
        """Determine which namespaces ``username`` has access to.

        Cheap heuristic for v1: list all namespaces using the user's token;
        K8s RBAC will filter to those they're authorised for.
        """
        try:
            from kubernetes_asyncio import client  # type: ignore
        except Exception:
            return []
        api_client = client.ApiClient(configuration=client.Configuration(
            host=client.Configuration().host,
            api_key={"authorization": f"Bearer {token}"},
        ))
        try:
            core = client.CoreV1Api(api_client)
            ns_list = await core.list_namespace()
            return [n.metadata.name for n in (ns_list.items or [])]
        except Exception as exc:  # pragma: no cover - cluster-dependent
            logger.debug("namespace discovery failed for %s: %s", username, exc)
            return []
        finally:
            await api_client.close()

    @staticmethod
    def _derive_roles(username: str, groups: list[str]) -> list[Role]:
        """Map K8s groups → runwhere-ai roles.

        v1 rule: any user whose groups contain ``runwhere:admin`` or
        ``system:masters`` is admin; everyone else is namespace_user.
        """
        admin_groups = {"runwhere:admin", "system:masters"}
        if any(g in admin_groups for g in groups):
            return [Role.ADMIN, Role.NAMESPACE_USER]
        return [Role.NAMESPACE_USER]

    # ── routes: begin / complete / logout ──────────────────────────────────

    async def begin_login(self, request: Request) -> Response:
        # Rendered by webui/pages/login.py — the provider only signals
        # which URL to use; HTML rendering belongs to the view layer.
        from src.webui.templating import templates  # local import to avoid cycle

        next_url = request.query_params.get("next", "/dashboard")
        return templates.TemplateResponse(
            request,
            "pages/login.html",
            {"next": next_url, "error": None},
        )

    async def complete_login(self, request: Request) -> Response:
        form = await request.form()
        token = (form.get("token") or "").strip()
        next_url = form.get("next") or "/dashboard"
        if not token:
            from src.webui.templating import templates

            return templates.TemplateResponse(
                request,
                "pages/login.html",
                {"next": next_url, "error": "missing"},
                status_code=400,
            )
        try:
            user = await self._whoami(token)
        except AuthError:
            from src.webui.templating import templates

            return templates.TemplateResponse(
                request,
                "pages/login.html",
                {"next": next_url, "error": "invalid"},
                status_code=401,
            )

        # Cache fresh (so first protected request is instant).
        await self._cache.put(token, user)

        response = RedirectResponse(url=next_url, status_code=302)
        response.set_cookie(
            CONFIG.session_cookie_name,
            value=token,
            httponly=True,
            secure=CONFIG.cookie_secure,
            samesite="strict",
            max_age=60 * 60 * 8,  # 8 hours
        )
        # Double-submit CSRF cookie (readable by JS in same-origin)
        import secrets

        response.set_cookie(
            CONFIG.csrf_cookie_name,
            value=secrets.token_urlsafe(32),
            httponly=False,
            secure=CONFIG.cookie_secure,
            samesite="strict",
            max_age=60 * 60 * 8,
        )
        return response

    async def logout(self, request: Request) -> Response:
        token = request.cookies.get(CONFIG.session_cookie_name)
        if token:
            await self._cache.evict(token)
        response = RedirectResponse(url=self.login_url, status_code=302)
        response.delete_cookie(CONFIG.session_cookie_name)
        response.delete_cookie(CONFIG.csrf_cookie_name)
        return response


# ─── v2 · OIDC stub ───────────────────────────────────────────────────────────

class OidcProvider:
    """Reserved for v2 (clarify Q1, option D — extension point only)."""

    kind = "oidc"

    @property
    def login_url(self) -> str:
        return "/oidc/start"

    async def authenticate(self, request: Request) -> User:
        raise NotImplementedError("OIDC reserved for v2")

    async def begin_login(self, request: Request) -> Response:
        raise NotImplementedError("OIDC reserved for v2")

    async def complete_login(self, request: Request) -> Response:
        raise NotImplementedError("OIDC reserved for v2")

    async def logout(self, request: Request) -> Response:
        raise NotImplementedError("OIDC reserved for v2")


# ─── DEV ONLY · auth bypass ───────────────────────────────────────────────────

class DevBypassProvider:
    """⚠️  DEV ONLY · returns a fake admin user for every request.

    Activated via env ``RWAI_AUTH_PROVIDER=bypass``. Intended for "let me look
    at the UI without setting up a real K8s token" sessions. Templates show a
    yellow "DEV MODE" banner whenever this is active so it cannot be confused
    with a real login. **Never ship to production.**
    """

    kind = "bypass"

    def __init__(self) -> None:
        self._fake_user = User(
            subject="dev-user",
            display_name="Dev User",
            namespaces=["default"],
            roles=[Role.ADMIN, Role.NAMESPACE_USER],
            token=None,
        )
        logger.warning(
            "⚠️  DevBypassProvider active — authentication is bypassed "
            "(set RWAI_AUTH_PROVIDER=bearer for real auth)"
        )

    @property
    def login_url(self) -> str:
        return "/login"

    async def authenticate(self, request: Request) -> User:
        return self._fake_user

    async def begin_login(self, request: Request) -> Response:
        # In bypass mode the "login page" simply jumps straight to next URL.
        next_url = request.query_params.get("next", "/dashboard")
        return RedirectResponse(next_url, status_code=302)

    async def complete_login(self, request: Request) -> Response:
        return RedirectResponse("/dashboard", status_code=302)

    async def logout(self, request: Request) -> Response:
        # No real session to clear; just bounce back home.
        return RedirectResponse("/dashboard", status_code=302)


# ─── factory ──────────────────────────────────────────────────────────────────

def make_auth_provider() -> AuthProvider:
    if CONFIG.auth_provider == "bypass":
        return DevBypassProvider()
    if CONFIG.auth_provider == "oidc":
        return OidcProvider()
    return BearerTokenProvider()
