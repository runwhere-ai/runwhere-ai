"""Contract tests for the i18n dictionary."""
from __future__ import annotations

import pytest

from src.console import i18n


def test_known_key_returns_chinese():
    assert i18n.t("auth.login.title") == "登录 runwhere-ai"


def test_unknown_key_returns_key_unchanged():
    assert i18n.t("does.not.exist") == "does.not.exist"


def test_has_known_and_unknown():
    assert i18n.has("auth.login.title") is True
    assert i18n.has("missing.key") is False


def test_keys_are_sorted_and_nonempty():
    ks = i18n.keys()
    assert len(ks) > 0
    assert ks == sorted(ks)


def test_no_keys_collide_with_themselves_as_values():
    """A common typo is `t("key") == "key"` which silently returns the fallback.
    Make sure no real value happens to equal its key."""
    for k in i18n.keys():
        assert i18n.t(k) != k, f"key {k!r} value equals its own name (probably a fallback)"


@pytest.mark.parametrize(
    "key",
    [
        "auth.login.title",
        "auth.login.token_label",
        "nav.notebooks",
        "nav.trainings",
        "nav.inferences",
        "nav.computes",
        "state.loading",
        "state.empty.title",
        "state.error.title",
        "conn.online",
        "conn.degraded",
        "why.recent_events",
    ],
)
def test_critical_keys_present(key):
    """These keys are referenced by templates/components — they must exist."""
    assert i18n.has(key), f"i18n key {key!r} is missing"
