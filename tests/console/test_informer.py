"""Contract tests for SharedInformer (research R-01).

We use a fake list_fn / watch_fn pair instead of a real K8s connection.
"""
from __future__ import annotations

import asyncio

import pytest

from src.console.informer import SharedInformer, _rv_geq
from src.console.models import Kind
from src.console.pubsub import TopicBus


def make_obj(ns: str, name: str, rv: str, **extra) -> dict:
    return {
        "namespace": ns,
        "name": name,
        "resource_version": rv,
        "labels": extra.get("labels", {}),
    }


@pytest.mark.asyncio
async def test_initial_list_populates_cache():
    items = [make_obj("ns1", "a", "10"), make_obj("ns1", "b", "11")]

    async def list_fn():
        return items, "11"

    async def watch_fn(rv):
        if False:  # pragma: no cover
            yield {}

    inf = SharedInformer(Kind.NOTEBOOK, list_fn=list_fn, watch_fn=watch_fn,
                         topic_bus=TopicBus())
    await inf.start()
    assert inf.ready
    assert inf.get("ns1", "a") == items[0]
    assert inf.latest_resource_version == "11"
    await inf.stop()


@pytest.mark.asyncio
async def test_watch_event_updates_cache_and_publishes():
    bus = TopicBus()
    sub = await bus.subscribe({("ns1", Kind.NOTEBOOK)})

    initial = [make_obj("ns1", "a", "10")]

    async def list_fn():
        return initial, "10"

    async def watch_fn(rv):
        # Yield one MODIFIED event then simulate a long-lived watch.
        yield {"type": "MODIFIED", "object": make_obj("ns1", "a", "20"), "resource_version": "20"}
        await asyncio.sleep(3600)

    inf = SharedInformer(Kind.NOTEBOOK, list_fn=list_fn, watch_fn=watch_fn,
                         topic_bus=bus)
    await inf.start()
    # Let the watch task drain.
    await asyncio.sleep(0.05)
    assert inf.latest_resource_version == "20"
    assert sub.queue.qsize() == 1
    evt = sub.queue.get_nowait()
    assert evt.type == "MODIFIED"
    assert evt.resource_version == "20"
    await inf.stop()


@pytest.mark.asyncio
async def test_delete_removes_from_cache():
    bus = TopicBus()

    async def list_fn():
        return [make_obj("ns1", "a", "10")], "10"

    async def watch_fn(rv):
        yield {"type": "DELETED", "object": make_obj("ns1", "a", "11"), "resource_version": "11"}
        await asyncio.sleep(3600)

    inf = SharedInformer(Kind.NOTEBOOK, list_fn=list_fn, watch_fn=watch_fn,
                         topic_bus=bus)
    await inf.start()
    await asyncio.sleep(0.05)
    assert inf.get("ns1", "a") is None
    await inf.stop()


@pytest.mark.asyncio
async def test_list_filters_by_namespace_and_labels():
    items = [
        make_obj("ns1", "a", "1", labels={"team": "ml"}),
        make_obj("ns1", "b", "2", labels={"team": "data"}),
        make_obj("ns2", "c", "3", labels={"team": "ml"}),
    ]

    async def list_fn():
        return items, "3"

    async def watch_fn(rv):
        if False:  # pragma: no cover
            yield {}

    inf = SharedInformer(Kind.NOTEBOOK, list_fn=list_fn, watch_fn=watch_fn,
                         topic_bus=TopicBus())
    await inf.start()
    assert len(inf.list()) == 3
    assert len(inf.list(namespace="ns1")) == 2
    assert {o["name"] for o in inf.list(filters={"team": "ml"})} == {"a", "c"}
    await inf.stop()


@pytest.mark.asyncio
async def test_wait_until_satisfied_immediately():
    async def list_fn():
        return [], "100"

    async def watch_fn(rv):
        if False:  # pragma: no cover
            yield {}

    inf = SharedInformer(Kind.NOTEBOOK, list_fn=list_fn, watch_fn=watch_fn,
                         topic_bus=TopicBus())
    await inf.start()
    assert await inf.wait_until("50", timeout=0.5) is True
    assert await inf.wait_until("100", timeout=0.5) is True
    await inf.stop()


@pytest.mark.asyncio
async def test_wait_until_times_out_then_event_releases():
    async def list_fn():
        return [], "10"

    fired = asyncio.Event()

    async def watch_fn(rv):
        # Delay one event a bit so wait_until has to actually wait.
        await fired.wait()
        yield {"type": "ADDED", "object": make_obj("ns", "x", "50"), "resource_version": "50"}

    inf = SharedInformer(Kind.NOTEBOOK, list_fn=list_fn, watch_fn=watch_fn,
                         topic_bus=TopicBus())
    await inf.start()
    # First call must time out.
    assert await inf.wait_until("99", timeout=0.05) is False
    # Now fire the event and the next wait_until should succeed.
    fired.set()
    await asyncio.sleep(0.05)
    assert await inf.wait_until("50", timeout=0.5) is True
    await inf.stop()


class TestRvGeq:
    def test_numeric(self):
        assert _rv_geq("20", "10") is True
        assert _rv_geq("10", "20") is False
        assert _rv_geq("10", "10") is True

    def test_empty_a_means_false(self):
        assert _rv_geq("", "10") is False

    def test_empty_b_means_true(self):
        assert _rv_geq("10", "") is True

    def test_non_numeric_falls_back_to_equality(self):
        assert _rv_geq("xyz", "xyz") is True
        assert _rv_geq("abc", "xyz") is False
