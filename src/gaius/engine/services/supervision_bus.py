"""In-process event bus feeding the EngineSupervision.Supervise stream.

The engine is the SOURCE of every supervision event (task lifecycle, admission
windows, positions, objective verdicts, incidents); the resident Nautilus dials
the engine and consumes them. This module is the seam between the emitting code
paths and the stream servicer: emitters call ``get_bus().publish(kind, **payload)``
at the SQL sites that change the truth (claim, heartbeat, completion, admission,
verdict, incident); the servicer subscribes and converts to protobuf.

Doctrine: bookkeeping never disturbs the run. ``publish`` is synchronous, never
raises, and drops the OLDEST event of a slow subscriber (counted, logged once per
100 drops — ``#SV.00000002.BUSDROP``). Payloads are flat, JSON-safe dicts; the
bus knows no protobuf. Modeled on ``workload_profile.WorkloadProfilePublisher``.

A bounded ring of recent events (by ``seq``) lets a reconnecting supervisor resume
from its last ``seq`` inside the same engine session without a table replay;
anything older comes from ``supervision_replay`` (the engine's tables are the
write-ahead log until the supervisor has acked the record).
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

GURU_BUSDROP = "#SV.00000002.BUSDROP"

QUEUE_MAXSIZE = 512
RING_MAXLEN = 20_000

# Event kinds (the EngineEvent oneof, minus the per-stream hello/heartbeat).
KIND_TASK = "task"
KIND_ADMISSION = "admission"
KIND_POSITION = "position"
KIND_OBJECTIVE = "objective"
KIND_INCIDENT = "incident"
KIND_SERVING = "serving"
KIND_DIRECTIVE_RESULT = "directive_result"
# (2026-09-06) Coordination Activities as the LOCAL engine saw them (→ ActivityEvent).
KIND_ACTIVITY = "activity"


def now_ms() -> int:
    return int(time.time() * 1000)


@dataclass(frozen=True)
class SupervisionEvent:
    seq: int
    at_unix_ms: int          # SOURCE timestamp (a row's own time), never emission time
    kind: str
    payload: dict[str, Any]
    replayed: bool = False


@dataclass
class _SubStats:
    delivered: int = 0
    dropped: int = 0


@dataclass
class SupervisionBus:
    """Fan-out of supervision events with a resume ring."""

    _seq: int = 0
    _subs: dict[int, tuple[asyncio.Queue, _SubStats]] = field(default_factory=dict)
    _ring: deque = field(default_factory=lambda: deque(maxlen=RING_MAXLEN))
    _dropped_total: int = 0
    session: int = field(default_factory=lambda: int(time.time()))

    # ── subscribers ─────────────────────────────────────────────────────────
    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=QUEUE_MAXSIZE)
        self._subs[id(q)] = (q, _SubStats())
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subs.pop(id(q), None)

    # ── publishing ──────────────────────────────────────────────────────────
    def publish(self, kind: str, *, at_unix_ms: int | None = None, **payload: Any) -> SupervisionEvent:
        """Emit one event to every subscriber. Synchronous; never raises."""
        self._seq += 1
        ev = SupervisionEvent(
            seq=self._seq,
            at_unix_ms=int(at_unix_ms if at_unix_ms is not None else now_ms()),
            kind=kind,
            payload=dict(payload),
        )
        self._ring.append(ev)
        for q, stats in list(self._subs.values()):
            self._offer(q, stats, ev)
        return ev

    def publish_to(self, q: asyncio.Queue, kind: str, *, at_unix_ms: int | None = None, **payload: Any) -> SupervisionEvent | None:
        """Emit one event to a single subscriber (per-session results)."""
        entry = self._subs.get(id(q))
        if entry is None:
            return None
        self._seq += 1
        ev = SupervisionEvent(
            seq=self._seq,
            at_unix_ms=int(at_unix_ms if at_unix_ms is not None else now_ms()),
            kind=kind,
            payload=dict(payload),
        )
        self._offer(entry[0], entry[1], ev)
        return ev

    def _offer(self, q: asyncio.Queue, stats: _SubStats, ev: SupervisionEvent) -> None:
        try:
            if q.full():
                try:
                    q.get_nowait()  # drop the OLDEST — the newest state is the truth
                except Exception:  # noqa: BLE001
                    pass
                stats.dropped += 1
                self._dropped_total += 1
                if stats.dropped % 100 == 1:
                    logger.warning(
                        "%s supervision subscriber slow: %d dropped (delivered %d)",
                        GURU_BUSDROP, stats.dropped, stats.delivered,
                    )
            q.put_nowait(ev)
            stats.delivered += 1
        except Exception as e:  # noqa: BLE001 — never disturb the emitter
            logger.debug("supervision bus offer failed: %s", e)

    # ── resume + stats ──────────────────────────────────────────────────────
    def ring_since(self, seq: int) -> list[SupervisionEvent] | None:
        """Events with seq > ``seq`` if the ring still covers them, else None
        (the caller must replay from tables)."""
        if not self._ring:
            return [] if seq >= self._seq else None
        oldest = self._ring[0].seq
        if seq + 1 < oldest:
            return None
        return [ev for ev in self._ring if ev.seq > seq]

    @property
    def seq(self) -> int:
        return self._seq

    def stats(self) -> dict[str, Any]:
        return {
            "seq": self._seq,
            "session": self.session,
            "subscribers": len(self._subs),
            "dropped_total": self._dropped_total,
            "ring": len(self._ring),
        }


_BUS: SupervisionBus | None = None


def init_bus() -> SupervisionBus:
    global _BUS
    if _BUS is None:
        _BUS = SupervisionBus()
    return _BUS


def get_bus() -> SupervisionBus | None:
    return _BUS


def publish(kind: str, **payload: Any) -> None:
    """Fire-and-forget emission for call sites that may run before the bus exists."""
    bus = _BUS
    if bus is None:
        return
    try:
        bus.publish(kind, **payload)
    except Exception:  # noqa: BLE001 — bookkeeping only
        logger.debug("supervision publish skipped", exc_info=True)
