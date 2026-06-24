"""TopicBus '*' wildcard: a ('*', kind) subscription matches any namespace of that
kind. Used by the list page's "all namespaces" view so it can live-update with a
single WS connection."""
from __future__ import annotations

from src.console.models import InformerEvent, Kind
from src.console.pubsub import TopicBus


def _evt(ns, kind, name):
    return InformerEvent(type="MODIFIED", kind=kind, namespace=ns, name=name,
                         resource_version="1", object={})


async def test_wildcard_matches_any_namespace():
    bus = TopicBus()
    sub = await bus.subscribe({("*", Kind.TRAINING)})
    await bus.publish(_evt("team-a", Kind.TRAINING, "x"))
    await bus.publish(_evt("team-b", Kind.TRAINING, "y"))
    await bus.publish(_evt("team-a", Kind.INFERENCE, "z"))   # 不同 kind → 不匹配
    assert sub.queue.qsize() == 2
    seen = {sub.queue.get_nowait().namespace, sub.queue.get_nowait().namespace}
    assert seen == {"team-a", "team-b"}


async def test_exact_subscription_stays_scoped():
    bus = TopicBus()
    sub = await bus.subscribe({("team-a", Kind.TRAINING)})
    await bus.publish(_evt("team-a", Kind.TRAINING, "x"))
    await bus.publish(_evt("team-b", Kind.TRAINING, "y"))    # 别的 ns → 不匹配
    assert sub.queue.qsize() == 1
    assert sub.queue.get_nowait().namespace == "team-a"
