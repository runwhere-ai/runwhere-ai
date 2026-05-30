"""Domain models for the runwhere-ai Service layer.

These are pure Pydantic / dataclasses with no I/O. They form the language in
which the rest of the Service layer (informer, pubsub, consistency, auth,
view_models) communicates.

Spec refs: FR-001 (User/Role), FR-101a ((ns,kind) subscription), FR-102 (Conflict).
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal, Optional
from uuid import uuid4

from pydantic import BaseModel, Field, SecretStr


# ─── Role / User ──────────────────────────────────────────────────────────────

class Role(str, Enum):
    NAMESPACE_USER = "namespace_user"
    ADMIN = "admin"


class User(BaseModel):
    """Authenticated subject. Carried via FastAPI Depends.

    ``token`` is held as SecretStr so it never leaks to logs / dumps.
    """

    subject: str = Field(description="Stable user identifier (e.g. SA name)")
    display_name: str = Field(default="", description="Human-readable name")
    namespaces: list[str] = Field(default_factory=list, description="Accessible K8s namespaces")
    roles: list[Role] = Field(default_factory=list)
    token: Optional[SecretStr] = Field(default=None, description="Bearer token (in-memory only)")

    @property
    def is_admin(self) -> bool:
        return Role.ADMIN in self.roles


# ─── Kind enum (mirrors gpuctl.constants.Kind) ────────────────────────────────
# We redefine to avoid hard-coupling at import time; values must stay aligned.

class Kind(str, Enum):
    NOTEBOOK = "notebook"
    TRAINING = "training"
    INFERENCE = "inference"
    COMPUTE = "compute"


# ─── Informer events ──────────────────────────────────────────────────────────

EventType = Literal["ADDED", "MODIFIED", "DELETED"]


class InformerEvent(BaseModel):
    """A single change event delivered by SharedInformer → TopicBus.

    The ``object`` payload is a generic dict for now; later phases may
    replace with concrete ViewModels per kind.
    """

    type: EventType
    kind: Kind
    namespace: str
    name: str
    resource_version: str
    object: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=datetime.utcnow)


# ─── Subscription / SubscriberHandle ──────────────────────────────────────────

class Subscription(BaseModel):
    """Logical subscription record (one per WS connection).

    Spec FR-101a: granularity = ``(namespace, kind)`` tuple set.
    """

    id: str = Field(default_factory=lambda: str(uuid4()))
    user_subject: str
    topics: set[tuple[str, Kind]] = Field(default_factory=set)
    connected_at: datetime = Field(default_factory=datetime.utcnow)
    last_heartbeat_at: datetime = Field(default_factory=datetime.utcnow)

    model_config = {"arbitrary_types_allowed": True}


# ─── Errors ───────────────────────────────────────────────────────────────────

class AuthError(Exception):
    """Raised when authentication cannot be established (→ 401)."""


class ForbiddenError(Exception):
    """Raised when user lacks permission for the requested resource (→ 403)."""


class ConflictError(Exception):
    """Optimistic-lock conflict (spec FR-102).

    Raised by ConsistencyGate when K8s returns 409. The HTTP layer
    translates this into 412 Precondition Failed with the current
    resource version exposed to the client (research R-03).
    """

    def __init__(
        self,
        message: str,
        current_resource_version: str,
        diff: Optional[dict[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        self.current_resource_version = current_resource_version
        self.diff = diff or {}


class PreconditionRequiredError(Exception):
    """Write attempted without an If-Match header (→ 428)."""
