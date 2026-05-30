"""Contract tests for src.console.status_palette.

Validates the full status→color mapping per PRD §5.3 and FR-022 / FR-112.
"""
from __future__ import annotations

import pytest

from src.console.status_palette import Color, StatusPalette


@pytest.mark.parametrize(
    "status,expected_color",
    [
        ("Running", "running"),
        ("Ready", "running"),
        ("Succeeded", "succeeded"),
        ("Pending", "pending"),
        ("ContainerCreating", "pending"),
        ("ImagePullBackOff", "warning"),
        ("InsufficientGPU", "warning"),
        ("Unschedulable", "warning"),
        ("CrashLoopBackOff", "danger"),
        ("OOMKilled", "danger"),
        ("Error", "danger"),
        ("Failed", "danger"),
        ("Stopped", "neutral"),
        ("Deleted", "neutral"),
        ("Unknown", "neutral"),
    ],
)
def test_color_mapping(status, expected_color):
    assert StatusPalette.color(status) == expected_color


def test_unknown_status_defaults_neutral():
    assert StatusPalette.color("FooBar") == "neutral"


def test_explain_in_chinese():
    assert "镜像" in StatusPalette.explain("ImagePullBackOff")
    assert "内存" in StatusPalette.explain("OOMKilled")
    assert "GPU" in StatusPalette.explain("InsufficientGPU")


def test_explain_unknown_returns_input():
    assert StatusPalette.explain("FooBar") == "FooBar"


@pytest.mark.parametrize(
    "status,terminal",
    [
        ("Running", False),
        ("Pending", False),
        ("Succeeded", True),
        ("Completed", True),
        ("Failed", True),
        ("Stopped", True),
        ("Deleted", True),
        ("Error", True),
    ],
)
def test_is_terminal(status, terminal):
    assert StatusPalette.is_terminal(status) is terminal


@pytest.mark.parametrize(
    "status,is_fail",
    [
        ("Running", False),
        ("Succeeded", False),
        ("Pending", False),
        ("ImagePullBackOff", True),
        ("CrashLoopBackOff", True),
        ("OOMKilled", True),
        ("InsufficientGPU", True),
        ("Failed", True),
    ],
)
def test_is_failure(status, is_fail):
    assert StatusPalette.is_failure(status) is is_fail


def test_is_recoverable_distinguishes_orange_from_red():
    # Orange tier = user-actionable
    assert StatusPalette.is_recoverable("ImagePullBackOff") is True
    assert StatusPalette.is_recoverable("InsufficientGPU") is True
    # Red tier = harder failures
    assert StatusPalette.is_recoverable("OOMKilled") is False
    assert StatusPalette.is_recoverable("CrashLoopBackOff") is False


def test_color_enum_values_match_css_classes():
    """Sanity: Color enum values are exactly the suffixes used in tokens.css."""
    expected = {"running", "succeeded", "pending", "warning", "danger", "neutral"}
    assert {c.value for c in Color} == expected
