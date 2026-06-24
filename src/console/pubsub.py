"""In-process (namespace, kind) pub/sub fan-out.

The TopicBus is the routing layer between SharedInformer (publisher of
K8s change events) and WebSocket subscribers (one per browser tab). It
implements the page-level subscription model from spec FR-101a.

Design constraints (research R-02):
  - subscribe() returns an async iterator of events filtered to the topics
  - per-subscriber bounded queue; overflow drops oldest + emits WARN
  - publishers do not block on slow subscribers
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import AsyncIterator, Optional
from uuid import uuid4

from src.config import CONFIG
from src.console.models import InformerEvent, Kind


logger = logging.getLogger(__name__)


@dataclass
class SubscriberHandle:
    """Handle returned to subscribers — pass back to ``unsubscribe()``."""

    id: str = field(default_factory=lambda: str(uuid4()))
    queue: asyncio.Queue = field(default_factory=asyncio.Queue)
    topics: set[tuple[str, Kind]] = field(default_factory=set)
    dropped: int = 0  # count of events dropped due to backpressure

    def matches(self, ns: str, kind: Kind) -> bool:
        # ("*", kind) = 通配订阅:列表「全部命名空间」视图用它,匹配该 kind 的任意 ns 事件。
        return (ns, kind) in self.topics or ("*", kind) in self.topics


class TopicBus:
    """Process-wide singleton — instantiate once and share via FastAPI Depends."""

    def __init__(self, *, queue_max: Optional[int] = None) -> None:
        self._subscribers: dict[str, SubscriberHandle] = {}
        self._queue_max = queue_max if queue_max is not None else CONFIG.pubsub_queue_max
        self._lock = asyncio.Lock()

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)

    async def subscribe(self, topics: set[tuple[str, Kind]]) -> SubscriberHandle:
        """Create a handle subscribed to the given topic set.

        Caller should ``await iterate(handle)`` and ``await unsubscribe(handle)``
        on disconnect.
        """
        handle = SubscriberHandle(
            queue=asyncio.Queue(maxsize=self._queue_max),
            topics=set(topics),
        )
        async with self._lock:
            self._subscribers[handle.id] = handle
        logger.debug("subscribed %s topics=%r", handle.id, handle.topics)
        return handle

    async def unsubscribe(self, handle: SubscriberHandle) -> None:
        async with self._lock:
            self._subscribers.pop(handle.id, None)
        if handle.dropped:
            logger.warning("subscriber %s dropped %d events due to backpressure",
                           handle.id, handle.dropped)

    async def publish(self, event: InformerEvent) -> None:
        """Fan out an event to all matching subscribers.

        Non-blocking from the publisher's perspective: if a subscriber's
        queue is full we drop the *oldest* event and increment its counter.
        """
        async with self._lock:
            subscribers = list(self._subscribers.values())
        for sub in subscribers:
            if not sub.matches(event.namespace, event.kind):
                continue
            try:
                sub.queue.put_nowait(event)
            except asyncio.QueueFull:
                # Drop oldest, then enqueue. This keeps recent events flowing.
                try:
                    sub.queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
                try:
                    sub.queue.put_nowait(event)
                except asyncio.QueueFull:
                    pass
                sub.dropped += 1

    async def iterate(self, handle: SubscriberHandle) -> AsyncIterator[InformerEvent]:
        """Yield events delivered to ``handle`` until cancelled.

        Cancellation (e.g. WebSocket disconnect) breaks out cleanly; caller
        must still call ``unsubscribe(handle)`` to release the slot.
        """
        try:
            while True:
                event = await handle.queue.get()
                yield event
        except asyncio.CancelledError:
            return


# Module-level singleton accessor — used by FastAPI dependency injection.
_BUS: Optional[TopicBus] = None


def get_topic_bus() -> TopicBus:
    global _BUS
    if _BUS is None:
        _BUS = TopicBus()
    return _BUS


def reset_for_tests() -> None:
    """Clear the module-level singleton between tests."""
    global _BUS
    _BUS = None
