"""Contract tests for ConsistencyGate (research R-03)."""
from __future__ import annotations

import pytest

from src.console.consistency import ConsistencyGate
from src.console.models import ConflictError, PreconditionRequiredError


class TestParseIfMatch:
    def test_strong_etag(self):
        assert ConsistencyGate.parse_if_match('"V123"') == "V123"

    def test_weak_etag(self):
        assert ConsistencyGate.parse_if_match('W/"V123"') == "V123"

    def test_whitespace_tolerated(self):
        assert ConsistencyGate.parse_if_match('  "V99"  ') == "V99"

    def test_missing_required_raises(self):
        with pytest.raises(PreconditionRequiredError):
            ConsistencyGate.parse_if_match(None)

    def test_missing_optional_returns_empty(self):
        assert ConsistencyGate.parse_if_match(None, required=False) == ""
        assert ConsistencyGate.parse_if_match("", required=False) == ""

    def test_malformed_raises(self):
        with pytest.raises(ValueError):
            ConsistencyGate.parse_if_match("V123")  # no quotes
        with pytest.raises(ValueError):
            ConsistencyGate.parse_if_match('"unclosed')


class TestFormatEtag:
    def test_basic(self):
        assert ConsistencyGate.format_etag("V123") == '"V123"'

    def test_already_quoted_idempotent(self):
        assert ConsistencyGate.format_etag('"V123"') == '"V123"'


class TestConditionalUpdate:
    @pytest.mark.asyncio
    async def test_success_returns_action_value(self):
        async def action():
            return "ok"
        result = await ConsistencyGate.conditional_update(
            action,
            expected_rv="V1",
            is_conflict=lambda e: False,
            current_rv_extractor=lambda e: None,
        )
        assert result == "ok"

    @pytest.mark.asyncio
    async def test_conflict_translates_to_conflict_error(self):
        class FakeK8s409(Exception):
            pass

        async def action():
            raise FakeK8s409("the server reports 409")

        with pytest.raises(ConflictError) as ei:
            await ConsistencyGate.conditional_update(
                action,
                expected_rv="V1",
                is_conflict=lambda e: isinstance(e, FakeK8s409),
                current_rv_extractor=lambda e: "V2",
            )
        assert ei.value.current_resource_version == "V2"

    @pytest.mark.asyncio
    async def test_non_conflict_exception_bubbles_up(self):
        class BadGateway(Exception):
            pass

        async def action():
            raise BadGateway("upstream")

        with pytest.raises(BadGateway):
            await ConsistencyGate.conditional_update(
                action,
                expected_rv="V1",
                is_conflict=lambda e: False,
                current_rv_extractor=lambda e: None,
            )


class TestToHttpStatus:
    def test_precondition_required(self):
        assert ConsistencyGate.to_http_status(PreconditionRequiredError()) == 428

    def test_conflict(self):
        assert ConsistencyGate.to_http_status(ConflictError("x", current_resource_version="V")) == 412

    def test_other(self):
        assert ConsistencyGate.to_http_status(ValueError("x")) == 500
