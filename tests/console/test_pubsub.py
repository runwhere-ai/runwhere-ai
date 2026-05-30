"""Contract tests for the TopicBus (FR-101a / research R-02)."""
from __future__ import annotations

import asyncio

import pytest

from src.console.models import InformerEvent, Kind
from src.console.pubsub import TopicBus, get_topic_bus, reset_for_tests


def make_event(ns: str, kind: Kind, name: str, rv: str = "V1", typ: str = "ADDED") -> InformerEvent:
    return InformerEvent(
        type=typ, kind=kind, namespace=ns, name=name, resource_version=rv
    )


@pytest.fixture(autouse=True)
def _reset_singleton():
    reset_for_tests()
    yield
    reset_for_tests()


@pytest.mark.asyncio
async def test_subscribe_filters_by_topic():
    bus = TopicBus()
    sub = await bus.subscribe({("ns1", Kind.NOTEBOOK)})

    await bus.publish(make_event("ns1", Kind.NOTEBOOK, "a"))
    await bus.publish(make_event("ns2", Kind.NOTEBOOK, "b"))    # wrong ns
    await bus.publish(make_event("ns1", Kind.TRAINING, "c"))    # wrong kind

    assert sub.queue.qsize() == 1
    evt = sub.queue.get_nowait()
    assert evt.name == "a"

    await bus.unsubscribe(sub)


@pytest.mark.asyncio
async def test_multiple_subscribers_independent():
    bus = TopicBus()
    s1 = await bus.subscribe({("ns1", Kind.NOTEBOOK)})
    s2 = await bus.subscribe({("ns1", Kind.NOTEBOOK), ("ns1", Kind.TRAINING)})

    await bus.publish(make_event("ns1", Kind.NOTEBOOK, "n1"))
    await bus.publish(make_event("ns1", Kind.TRAINING, "t1"))

    assert s1.queue.qsize() == 1
    assert s2.queue.qsize() == 2


@pytest.mark.asyncio
async def test_unsubscribe_removes():
    bus = TopicBus()
    s = await bus.subscribe({("ns1", Kind.NOTEBOOK)})
    assert bus.subscriber_count == 1
    await bus.unsubscribe(s)
    assert bus.subscriber_count == 0


@pytest.mark.asyncio
async def test_backpressure_drops_oldest():
    bus = TopicBus(queue_max=3)
    sub = await bus.subscribe({("ns", Kind.NOTEBOOK)})

    for i in range(5):
        await bus.publish(make_event("ns", Kind.NOTEBOOK, f"item-{i}", rv=f"V{i}"))

    # Queue must remain bounded.
    assert sub.queue.qsize() == 3
    assert sub.dropped == 2

    # Newest items must survive.
    items = []
    while not sub.queue.empty():
        items.append(sub.queue.get_nowait().name)
    assert items[-1] == "item-4"


@pytest.mark.asyncio
async def test_iterate_yields_events():
    bus = TopicBus()
    sub = await bus.subscribe({("ns", Kind.NOTEBOOK)})

    received: list[str] = []

    async def consumer():
        async for evt in bus.iterate(sub):
            received.append(evt.name)
            if len(received) == 2:
                break

    task = asyncio.create_task(consumer())
    await asyncio.sleep(0)  # let consumer reach `await get()`
    await bus.publish(make_event("ns", Kind.NOTEBOOK, "x"))
    await bus.publish(make_event("ns", Kind.NOTEBOOK, "y"))
    await asyncio.wait_for(task, timeout=1)
    assert received == ["x", "y"]


@pytest.mark.asyncio
async def test_singleton_accessor():
    a = get_topic_bus()
    b = get_topic_bus()
    assert a is b
