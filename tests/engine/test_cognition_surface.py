"""CognitionSurface aggregates are honest — no invented warehouses."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from gaius.engine.services.cognition_buffer import NEXT_QUESTION_RESERVE_TOKENS
from gaius.engine.services.cognition_surface import (
    SURFACE_GURU_NODB,
    SURFACE_GURU_WINDOW,
    build_cognition_surface,
    concentration,
    normalize_window,
    thoughts_per_cycle,
)


def test_concentration_empty() -> None:
    assert concentration([]) == ("", 0.0)


def test_concentration_dominant_stream() -> None:
    stream, pct = concentration([("pattern", 3), ("curiosity", 1)])
    assert stream == "pattern"
    assert pct == 75.0


def test_thoughts_per_cycle() -> None:
    assert thoughts_per_cycle(10, 0) == 0.0
    assert thoughts_per_cycle(10, 4) == 2.5


def test_normalize_window_default_and_bounds() -> None:
    assert normalize_window(0) == 365
    with pytest.raises(ValueError, match="COG.00000026"):
        normalize_window(-1)
    with pytest.raises(ValueError, match="COG.00000026"):
        normalize_window(4000)


@pytest.mark.asyncio
async def test_surface_fails_fast_without_pool() -> None:
    with pytest.raises(RuntimeError, match="COG.00000025"):
        await build_cognition_surface(
            None,
            window_days=365,
            thought_limit=80,
            stream="",
            status={},
        )
    assert "NODB" in SURFACE_GURU_NODB
    assert "BADWINDOW" in SURFACE_GURU_WINDOW


class _Conn:
    def __init__(self, script: list[object]) -> None:
        self._script = list(script)

    async def fetchrow(self, _sql: str, *_args: object) -> object:
        return self._script.pop(0)

    async def fetch(self, _sql: str, *_args: object) -> object:
        return self._script.pop(0)


class _Pool:
    def __init__(self, script: list[object]) -> None:
        self._conn = _Conn(script)

    def acquire(self) -> "_Acquire":
        return _Acquire(self._conn)


class _Acquire:
    def __init__(self, conn: _Conn) -> None:
        self._conn = conn

    async def __aenter__(self) -> _Conn:
        return self._conn

    async def __aexit__(self, *_exc: object) -> None:
        return None


def _thought_row(title: str, kind: str, salience: float) -> dict:
    return {
        "id": "00000000-0000-0000-0000-000000000001",
        "thought_type": kind,
        "title": title,
        "summary": "brief",
        "content": "full",
        "salience": salience,
        "generation": 0,
        "note_path": "scratch/x.md",
        "created_at": datetime(2026, 8, 16, 15, 0, tzinfo=timezone.utc),
    }


@pytest.mark.asyncio
async def test_surface_maps_window_rows() -> None:
    from datetime import timedelta

    created = datetime.now(timezone.utc) - timedelta(days=14)
    created = created.replace(hour=0, minute=0, second=0, microsecond=0)
    script = [
        {"thoughts": 4, "streams": 2, "active_days": 1},
        {"cycles": 2},
        [{"thought_type": "pattern", "n": 3}, {"thought_type": "curiosity", "n": 1}],
        [{"t": created, "n": 4, "tokens": 120, "salience_max": 0.9}],
        [{"t": created, "n": 2}],
        [{"weekday": 0, "hour": 15, "n": 4}],
        [_thought_row("recent one", "pattern", 0.4)],
        [_thought_row("top one", "pattern", 0.9)],
    ]
    snap = await build_cognition_surface(
        _Pool(script),
        window_days=365,
        thought_limit=80,
        stream="",
        status={"running": True, "cycles_completed": 12, "current_task": ""},
    )
    assert snap.running is True
    assert snap.thoughts == 4
    assert snap.streams == 2
    assert snap.cycles_in_window == 2
    assert snap.thoughts_per_cycle == 2.0
    assert snap.concentration_stream == "pattern"
    assert snap.concentration_pct == 75.0
    assert snap.reserve_tokens == NEXT_QUESTION_RESERVE_TOKENS
    assert snap.project == "gaius"
    assert snap.unit == "cognition"
    assert snap.recent[0].title == "recent one"
    assert snap.top[0].salience == 0.9
    assert snap.hours[0].hour == 15
    # Scale-aware series: 365d resolves to week buckets, zero-filled,
    # with the scripted rows folded into their containing bucket.
    assert snap.interval == "week"
    assert snap.days == []  # legacy field superseded
    assert 50 <= len(snap.buckets) <= 55
    assert sum(b.thoughts for b in snap.buckets) == 4
    hit = next(b for b in snap.buckets if b.thoughts == 4)
    assert hit.cycles == 2
    assert hit.tokens == 120
    assert hit.salience_max == 0.9
    assert snap.range_end_ms > snap.range_start_ms
    assert snap.effective_end_ms == snap.range_end_ms
    assert snap.bucket_seconds == 604800
    # Half-open tiling: buckets abut exactly
    for prev, cur in zip(snap.buckets, snap.buckets[1:]):
        assert prev.end_ms == cur.start_ms


@pytest.mark.asyncio
async def test_surface_hour_window_via_grammar() -> None:
    script = [
        {"thoughts": 0, "streams": 0, "active_days": 0},
        {"cycles": 0},
        [],
        [],
        [],
        [],
        [],
        [],
    ]
    snap = await build_cognition_surface(
        _Pool(script),
        window_days=0,
        thought_limit=80,
        stream="",
        status={},
        window="24h",
    )
    assert snap.interval == "hour"
    assert 24 <= len(snap.buckets) <= 25
    assert all(b.thoughts == 0 for b in snap.buckets)  # zero-filled, honest


@pytest.mark.asyncio
async def test_fetch_thought_detail_maps_and_chains() -> None:
    from datetime import timedelta

    from gaius.engine.services.cognition_surface import fetch_thought_detail

    now = datetime.now(timezone.utc)

    def _detail_row(tid: str, gen: int, pred: str | None) -> dict:
        return {
            "id": tid,
            "thought_type": "pattern",
            "title": f"g{gen}",
            "summary": "s",
            "content": "full reasoning text",
            "salience": 0.5,
            "confidence": 0.7,
            "novelty": 0.2,
            "generation": gen,
            "created_at": now - timedelta(minutes=10 - gen),
            "note_path": "scratch/x.md",
            "status": "active",
            "generator_model": "Qwen/Qwen3.8-27B",
            "tokens_used": 321,
            "domains": ["signals", "kudu"],
            "thought_chain_id": "c1",
            "predecessor_id": pred,
        }

    script = [
        _detail_row("t2", 1, "t1"),
        [_detail_row("t2", 1, "t1"), _detail_row("t1", 0, None)],
    ]
    detail, chain = await fetch_thought_detail(_Pool(script), "t2")
    assert detail["content"] == "full reasoning text"
    assert detail["tokens_used"] == 321
    assert detail["domains"] == ["signals", "kudu"]
    assert detail["predecessor_id"] == "t1"
    assert [c["id"] for c in chain] == ["t1", "t2"] or [c["id"] for c in chain] == ["t2", "t1"]

    with pytest.raises(ValueError, match="COG.00000035"):
        await fetch_thought_detail(_Pool([]), "")


@pytest.mark.asyncio
async def test_servicer_surface_nosvc() -> None:
    from gaius.engine.generated import CognitionSurfaceRequest
    from gaius.engine.grpc.servicers.gaius_servicer import GaiusServicer

    services = SimpleNamespace(cognition_service=None)
    servicer = GaiusServicer(services)  # type: ignore[arg-type]
    resp = await servicer.CognitionSurface(CognitionSurfaceRequest(), MagicMock())
    assert "COG.00000024.NOSVC" in resp.error


@pytest.mark.asyncio
async def test_servicer_surface_maps_snapshot() -> None:
    from gaius.engine.generated import CognitionSurfaceRequest
    from gaius.engine.grpc.servicers.gaius_servicer import GaiusServicer
    from gaius.engine.services.cognition_surface import (
        CognitionSurface,
        SurfaceThought,
    )

    snap = CognitionSurface(
        running=True,
        cycles_completed=3,
        cycles_in_window=1,
        last_cycle_timestamp_ms=1,
        current_task="",
        thoughts=1,
        streams=1,
        active_days=1,
        thoughts_per_cycle=1.0,
        concentration_stream="pattern",
        concentration_pct=100.0,
        reserve_tokens=NEXT_QUESTION_RESERVE_TOKENS,
        project="gaius",
        unit="cognition",
        recent=[
            SurfaceThought(
                id="t1",
                thought_type="pattern",
                title="hello",
                summary="s",
                salience=0.5,
                generation=0,
                timestamp_ms=1,
                note_path="",
            )
        ],
    )
    cognition = SimpleNamespace(surface=AsyncMock(return_value=snap))
    servicer = GaiusServicer(SimpleNamespace(cognition_service=cognition))  # type: ignore[arg-type]
    resp = await servicer.CognitionSurface(
        CognitionSurfaceRequest(window_days=30),
        MagicMock(),
    )
    assert resp.error == ""
    assert resp.thoughts == 1
    assert resp.recent[0].title == "hello"
    cognition.surface.assert_awaited_once()
