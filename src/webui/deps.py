"""FastAPI dependency providers.

This is the single composition root for runwhere-ai's web layer:
authentication, informers, pubsub, view models, etc. all get injected
here so route handlers stay thin and tests can override at will.

Spec FR-116, FR-117.
"""
from __future__ import annotations

from typing import Optional

from fastapi import Depends, HTTPException, Request

from src.console.auth import AuthProvider, make_auth_provider
from src.console.models import AuthError, ForbiddenError, Role, User
from src.console.pubsub import TopicBus, get_topic_bus


# ─── Singletons ──────────────────────────────────────────────────────────────

_AUTH_PROVIDER: Optional[AuthProvider] = None


def get_auth_provider() -> AuthProvider:
    global _AUTH_PROVIDER
    if _AUTH_PROVIDER is None:
        _AUTH_PROVIDER = make_auth_provider()
    return _AUTH_PROVIDER


def reset_auth_provider_for_tests() -> None:
    global _AUTH_PROVIDER
    _AUTH_PROVIDER = None


def get_pubsub() -> TopicBus:
    return get_topic_bus()


# ─── Auth & RBAC ─────────────────────────────────────────────────────────────

async def get_current_user(
    request: Request,
    auth: AuthProvider = Depends(get_auth_provider),
) -> User:
    """Resolve the authenticated user, or raise 401.

    For HTMX requests we want the global error handler to translate this
    into an ``HX-Redirect`` header so the client transparently navigates
    to the login page (auth-provider §5).
    """
    try:
        return await auth.authenticate(request)
    except AuthError:
        raise HTTPException(status_code=401, detail="not_authenticated")


async def require_admin(user: User = Depends(get_current_user)) -> User:
    if Role.ADMIN not in user.roles:
        raise HTTPException(status_code=403, detail="admin_only")
    return user


async def require_namespace_access(
    namespace: str,
    user: User = Depends(get_current_user),
) -> User:
    """For operations scoped to a single namespace (FR-002)."""
    if Role.ADMIN in user.roles:
        return user
    if namespace not in user.namespaces:
        raise ForbiddenError(f"no access to namespace {namespace!r}")
    return user
