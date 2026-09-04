"""The supervision event bus: monotonic seq, bounded drop-oldest, never raises."""

from __future__ import annotations

import asyncio

from gaius.engine.services.supervision_bus import QUEUE_MAXSIZE, SupervisionBus


def test_publish_is_monotonic_and_fans_out() -> None:
    bus = SupervisionBus()
    q1, q2 = bus.subscribe(), bus.subscribe()
    a = bus.publish("task", task_id=1, state="CLAIMED")
    b = bus.publish("task", task_id=1, state="COMPLETED")
    assert (a.seq, b.seq) == (1, 2)
    assert q1.get_nowait().seq == 1 and q2.get_nowait().seq == 1
    assert q1.get_nowait().payload["state"] == "COMPLETED"
    bus.unsubscribe(q2)
    bus.publish("task", task_id=2, state="CLAIMED")
    assert q1.qsize() == 1 and q2.qsize() == 1  # q2 no longer fed


def test_slow_subscriber_drops_oldest_and_counts() -> None:
    bus = SupervisionBus()
    q = bus.subscribe()
    for i in range(QUEUE_MAXSIZE + 5):
        bus.publish("task", task_id=i, state="HEARTBEAT")
    assert q.qsize() == QUEUE_MAXSIZE
    assert q.get_nowait().payload["task_id"] == 5  # the five oldest were dropped
    assert bus.stats()["dropped_total"] == 5


def test_ring_resume_inside_session() -> None:
    bus = SupervisionBus()
    for i in range(10):
        bus.publish("task", task_id=i, state="CLAIMED")
    tail = bus.ring_since(7)
    assert [e.seq for e in tail] == [8, 9, 10]
    assert bus.ring_since(10) == []


def test_publish_to_is_per_subscriber() -> None:
    bus = SupervisionBus()
    q1, q2 = bus.subscribe(), bus.subscribe()
    bus.publish_to(q1, "directive_result", directive_id="d1", accepted=True)
    assert q1.qsize() == 1 and q2.qsize() == 0
    assert q1.get_nowait().payload["directive_id"] == "d1"


def test_source_timestamp_is_kept() -> None:
    bus = SupervisionBus()
    ev = bus.publish("task", at_unix_ms=1_700_000_000_000, task_id=1, state="COMPLETED")
    assert ev.at_unix_ms == 1_700_000_000_000


def test_asyncio_queue_consumption() -> None:
    async def go() -> int:
        bus = SupervisionBus()
        q = bus.subscribe()
        bus.publish("objective", objective="x", verdict="FAIL")
        ev = await asyncio.wait_for(q.get(), 1)
        return ev.seq

    assert asyncio.run(go()) == 1
