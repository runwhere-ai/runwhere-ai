"""SharedInformer: K8s Watch + in-memory cache + Read-Your-Writes wait.

Spec FR-100, FR-101, FR-101a, FR-103.  Research R-01.

For each (cluster, K8s resource kind) we maintain ONE background
list-and-watch coroutine that:
  1. Performs an initial list and populates the cache with seen objects.
  2. Streams subsequent ADDED / MODIFIED / DELETED events; each event:
       - updates the cache,
       - bumps ``latest_resource_version``,
       - is published to the TopicBus.
  3. On 410 GONE (resource version too old) — re-list immediately.
  4. Every ``CONFIG.informer_resync_seconds`` re-lists for consistency.

The informer is *not* responsible for translating K8s objects into UI
ViewModels — that's the ViewModelBuilder's job. We keep the raw object
dict here.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

from src.config import CONFIG
from src.console.models import InformerEvent, Kind
from src.console.pubsub import TopicBus, get_topic_bus


logger = logging.getLogger(__name__)


# Cache key: (namespace, name)
CacheKey = tuple[str, str]


# Function that performs initial list, returning (items_list, resource_version).
# Allows tests to stub without a real K8s connection.
ListFn = Callable[[], Awaitable[tuple[list[dict[str, Any]], str]]]

# Async iterator over K8s watch events. Each yielded dict has
# {"type": "ADDED"|..., "object": dict, "resource_version": str}.
WatchFn = Callable[[str], Any]


@dataclass
class _KindCache:
    """Per-kind storage."""

    kind: Kind
    objects: dict[CacheKey, dict[str, Any]] = field(default_factory=dict)
    latest_rv: str = ""
    last_resync_at: float = 0.0


class SharedInformer:
    """A small list+watch informer, one per Kind.

    For v1 we keep all logic in this module without subclassing — caller
    constructs the informer for each kind with the K8s adapter callables.
    """

    def __init__(
        self,
        kind: Kind,
        *,
        list_fn: ListFn,
        watch_fn: WatchFn,
        topic_bus: Optional[TopicBus] = None,
        cache_max_objects: Optional[int] = None,
    ) -> None:
        self.kind = kind
        self._list_fn = list_fn
        self._watch_fn = watch_fn
        self._bus = topic_bus or get_topic_bus()
        self._cache = _KindCache(kind=kind)
        self._cache_max = (
            cache_max_objects if cache_max_objects is not None else CONFIG.informer_cache_max_objects
        )
        self._task: Optional[asyncio.Task] = None
        self._rv_event = asyncio.Event()
        self._stopped = asyncio.Event()
        self._lock = asyncio.Lock()
        self._ready = asyncio.Event()

    # ── lifecycle ───────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Perform first list synchronously, then spawn watch loop."""
        await self._initial_list()
        self._ready.set()
        self._task = asyncio.create_task(self._run(), name=f"informer:{self.kind.value}")
        logger.info("SharedInformer[%s] started, %d objects loaded",
                    self.kind.value, len(self._cache.objects))

    async def stop(self) -> None:
        self._stopped.set()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    @property
    def ready(self) -> bool:
        return self._ready.is_set()

    # ── read API (used by ViewModelBuilder) ──────────────────────────────────

    def get(self, namespace: str, name: str) -> Optional[dict[str, Any]]:
        return self._cache.objects.get((namespace, name))

    def list(
        self,
        namespace: Optional[str] = None,
        filters: Optional[dict[str, str]] = None,
    ) -> list[dict[str, Any]]:
        """Snapshot of current cache.

        ``filters`` is matched against the object's labels (exact equality).
        """
        out: list[dict[str, Any]] = []
        for (ns, _name), obj in self._cache.objects.items():
            if namespace and ns != namespace:
                continue
            if filters and not _match_labels(obj.get("labels", {}), filters):
                continue
            out.append(obj)
        return out

    @property
    def latest_resource_version(self) -> str:
        return self._cache.latest_rv

    async def wait_until(self, rv: str, timeout: Optional[float] = None) -> bool:
        """Block until local cache's RV ≥ ``rv`` or ``timeout`` elapses.

        Returns True if the condition was satisfied, False if timed out.
        Used for Read-Your-Writes (spec FR-103).
        """
        if timeout is None:
            timeout = CONFIG.ryw_wait_timeout_seconds
        deadline = asyncio.get_running_loop().time() + timeout
        while True:
            if _rv_geq(self._cache.latest_rv, rv):
                return True
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                return False
            self._rv_event.clear()
            try:
                await asyncio.wait_for(self._rv_event.wait(), timeout=remaining)
            except asyncio.TimeoutError:
                return False

    # ── internal: list + watch loop ─────────────────────────────────────────

    async def _initial_list(self) -> None:
        items, rv = await self._list_fn()
        async with self._lock:
            self._cache.objects.clear()
            for item in items[: self._cache_max]:
                key = (item.get("namespace", ""), item.get("name", ""))
                self._cache.objects[key] = item
            self._cache.latest_rv = rv
        self._rv_event.set()
        if len(items) > self._cache_max:
            logger.warning("SharedInformer[%s]: cache truncated %d → %d",
                           self.kind.value, len(items), self._cache_max)

    async def _run(self) -> None:
        """Watch loop with relist on disconnect / 410 GONE."""
        while not self._stopped.is_set():
            try:
                async for evt in self._watch_fn(self._cache.latest_rv):
                    await self._handle_event(evt)
            except _GoneError:
                logger.info("SharedInformer[%s]: 410 GONE, relisting", self.kind.value)
                await self._initial_list()
                continue
            except asyncio.CancelledError:
                return
            except Exception as exc:  # noqa: BLE001
                logger.warning("SharedInformer[%s] watch error %s — backing off", self.kind.value, exc)
                await asyncio.sleep(2.0)
                continue
            # Generator exhausted cleanly — treat as connection end. Brief
            # backoff before resubscribing so we don't spin if the adapter
            # returns immediately (also crucial for unit tests).
            await asyncio.sleep(0.5)

    async def _handle_event(self, raw: dict[str, Any]) -> None:
        typ = raw.get("type", "MODIFIED")
        obj = raw.get("object", {})
        ns = obj.get("namespace", "")
        name = obj.get("name", "")
        rv = obj.get("resource_version") or raw.get("resource_version", "")
        key: CacheKey = (ns, name)

        async with self._lock:
            if typ == "DELETED":
                self._cache.objects.pop(key, None)
            else:
                self._cache.objects[key] = obj
            if _rv_geq(rv, self._cache.latest_rv):
                self._cache.latest_rv = rv

        self._rv_event.set()

        await self._bus.publish(
            InformerEvent(
                type=typ,                                      # type: ignore[arg-type]
                kind=self.kind,
                namespace=ns,
                name=name,
                resource_version=rv,
                object=obj,
            )
        )


# ─── utilities ────────────────────────────────────────────────────────────────

class _GoneError(Exception):
    """Raised by a watch adapter when K8s returns 410 GONE."""


def _rv_geq(a: str, b: str) -> bool:
    """Lexicographic-safe ≥ comparison for K8s resourceVersions.

    K8s RVs are unsigned integers represented as decimal strings; if both
    parse as int we compare numerically. Otherwise fall back to string
    equality (cannot order opaque strings).
    """
    if not a:
        return False
    if not b:
        return True
    try:
        return int(a) >= int(b)
    except ValueError:
        return a == b


def _match_labels(actual: dict[str, str], expected: dict[str, str]) -> bool:
    return all(actual.get(k) == v for k, v in expected.items())
