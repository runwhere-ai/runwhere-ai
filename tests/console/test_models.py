"""Contract tests for src.console.models."""
from __future__ import annotations

import pytest

from src.console.models import (
    AuthError,
    ConflictError,
    InformerEvent,
    Kind,
    PreconditionRequiredError,
    Role,
    Subscription,
    User,
)


class TestUser:
    def test_minimal_user(self):
        u = User(subject="alice")
        assert u.subject == "alice"
        assert u.roles == []
        assert u.is_admin is False
        assert u.token is None

    def test_admin_flag(self):
        u = User(subject="bob", roles=[Role.ADMIN])
        assert u.is_admin is True

    def test_token_is_secret(self):
        u = User(subject="alice", token="super-secret")
        # SecretStr repr must NOT leak token (spec FR-001 + security)
        assert "super-secret" not in repr(u)
        assert u.token.get_secret_value() == "super-secret"


class TestInformerEvent:
    def test_required_fields(self):
        e = InformerEvent(
            type="ADDED",
            kind=Kind.NOTEBOOK,
            namespace="ns",
            name="nb1",
            resource_version="V100",
        )
        assert e.type == "ADDED"
        assert e.kind == Kind.NOTEBOOK
        assert e.resource_version == "V100"

    def test_invalid_event_type_rejected(self):
        with pytest.raises(Exception):
            InformerEvent(
                type="WEIRD",  # not in EventType literal
                kind=Kind.NOTEBOOK,
                namespace="ns",
                name="nb1",
                resource_version="V100",
            )


class TestSubscription:
    def test_default_id_unique(self):
        s1 = Subscription(user_subject="u")
        s2 = Subscription(user_subject="u")
        assert s1.id != s2.id

    def test_topics_can_be_set(self):
        s = Subscription(user_subject="u", topics={("ns1", Kind.NOTEBOOK), ("ns1", Kind.TRAINING)})
        assert ("ns1", Kind.NOTEBOOK) in s.topics
        assert len(s.topics) == 2


class TestErrors:
    def test_conflict_error_carries_current_rv(self):
        e = ConflictError("conflict", current_resource_version="V200", diff={"replicas": [1, 2]})
        assert e.current_resource_version == "V200"
        assert e.diff == {"replicas": [1, 2]}

    def test_auth_error_is_exception(self):
        with pytest.raises(AuthError):
            raise AuthError("nope")

    def test_precondition_required(self):
        with pytest.raises(PreconditionRequiredError):
            raise PreconditionRequiredError()
