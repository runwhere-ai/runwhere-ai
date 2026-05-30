"""HTTP-level optimistic locking and Read-Your-Writes gate.

Maps K8s ``resourceVersion`` semantics onto standard HTTP headers
(``ETag`` / ``If-Match``), and translates K8s 409 Conflict into the
HTTP-standard 412 Precondition Failed (research R-03).

Spec refs: FR-102, FR-103.
"""
from __future__ import annotations

import re
from typing import Awaitable, Callable, Optional, TypeVar

from src.console.models import (
    ConflictError,
    PreconditionRequiredError,
)


T = TypeVar("T")


# ETag form: an opaque-quoted string; we use the resourceVersion verbatim.
# RFC 7232: ETag = entity-tag = [ weak ] opaque-tag
#                  weak       = %x57.2F ; "W/"
#                  opaque-tag = DQUOTE *etagc DQUOTE
_ETAG_RE = re.compile(r'^(?:W/)?"([^"]+)"$')


class ConsistencyGate:
    """Stateless utility class. All methods are static / pure where possible."""

    @staticmethod
    def parse_if_match(header: Optional[str], *, required: bool = True) -> str:
        """Extract the resourceVersion from an ``If-Match`` header.

        Args:
            header: raw header value, e.g. ``W/"V123"`` or ``"V123"``.
            required: if True, raise PreconditionRequiredError when missing.

        Returns:
            The resourceVersion (without quotes / weak marker).

        Raises:
            PreconditionRequiredError: header missing and ``required=True``.
            ValueError: header present but malformed.
        """
        if not header:
            if required:
                raise PreconditionRequiredError("If-Match header is required for this write")
            return ""
        m = _ETAG_RE.match(header.strip())
        if not m:
            raise ValueError(f"Malformed If-Match header: {header!r}")
        return m.group(1)

    @staticmethod
    def format_etag(rv: str) -> str:
        """Format a resourceVersion as a strong ETag header value."""
        # Guard against accidentally double-quoting if caller passes "V123" already.
        if rv.startswith('"') and rv.endswith('"'):
            return rv
        return f'"{rv}"'

    @staticmethod
    async def conditional_update(
        action: Callable[[], Awaitable[T]],
        expected_rv: str,
        *,
        is_conflict: Callable[[Exception], bool],
        current_rv_extractor: Callable[[Exception], Optional[str]],
    ) -> T:
        """Run ``action()`` and translate K8s 409 → ConflictError.

        The two callbacks let us stay decoupled from the kubernetes-asyncio
        exception types (which differ from kubernetes-client). Caller
        provides:

          - ``is_conflict(exc)``      → True iff exc represents a 409 Conflict
          - ``current_rv_extractor(exc)`` → returns the server's current
                                            resourceVersion, or None if unknown

        ``expected_rv`` is recorded in the ConflictError so the UI's "compare
        and merge" dialog can fetch the latest version and diff against it
        (spec FR-102).
        """
        try:
            return await action()
        except Exception as exc:  # noqa: BLE001  (caller decides via is_conflict)
            if is_conflict(exc):
                current = current_rv_extractor(exc) or ""
                raise ConflictError(
                    message="Resource was modified by another writer",
                    current_resource_version=current,
                ) from exc
            raise

    @staticmethod
    def to_http_status(exc: Exception) -> int:
        """Map a runwhere-ai exception to its HTTP status code."""
        if isinstance(exc, PreconditionRequiredError):
            return 428
        if isinstance(exc, ConflictError):
            return 412
        return 500
