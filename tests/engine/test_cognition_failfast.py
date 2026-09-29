"""Fail-fast guards for the cognition cycle and inference timeouts.

Pins the 2026-08-31 house-of-cards fix: a 30s default deadline on
Scheduler.complete + a fail-open swallow turned 16 days of timed-out
cognition cycles into "success" with zero thoughts.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from gaius.client.grpc_client import GrpcClientConfig, GrpcEngineClient


def _client(**overrides) -> GrpcEngineClient:
    # __new__ + config: resolve_timeout is pure config logic; skip __init__
    # so the test never touches channels.
    c = GrpcEngineClient.__new__(GrpcEngineClient)
    c.config = GrpcClientConfig(**overrides)
    return c


def test_resolve_timeout_explicit_wins() -> None:
    c = _client()
    assert c.resolve_timeout("Scheduler", "complete", 7.0) == 7.0
    assert c.resolve_timeout("Orchestrator", "status", 7.0) == 7.0


def test_resolve_timeout_inference_gets_inference_deadline() -> None:
    # No params → assumed 2048 budget → the scaled outer net (2048/4+240),
    # never below the configured floor.
    c = _client(timeout=30.0, inference_timeout=480.0)
    assert c.resolve_timeout("Scheduler", "complete", None) == 2048 / 4 + 240
    assert c.resolve_timeout("Scheduler", "evaluate", None) == 2048 / 4 + 240


def test_resolve_timeout_scales_with_max_tokens() -> None:
    """Outer safety net scales with the generation budget and is generous:
    the real supervision is engine-side token-progress stall detection."""
    c = _client(timeout=30.0, inference_timeout=480.0)
    assert c.resolve_timeout(
        "Scheduler", "complete", None, {"max_tokens": 4096}
    ) == 4096 / 4 + 240
    assert c.resolve_timeout(
        "Scheduler", "complete", None, {"max_tokens": 64}
    ) == 480.0


def test_resolve_timeout_non_inference_gets_base() -> None:
    c = _client(timeout=30.0, inference_timeout=480.0)
    assert c.resolve_timeout("Scheduler", "status", None) == 30.0
    assert c.resolve_timeout("Orchestrator", "complete", None) == 30.0


class _RaisingClient:
    async def call(self, *a, **k):
        raise TimeoutError("Request Scheduler.complete timed out")


class _Conn:
    def __init__(self, script: list[object]) -> None:
        self._script = list(script)

    async def fetch(self, _sql: str, *_args: object) -> object:
        return self._script.pop(0)

    async def fetchrow(self, _sql: str, *_args: object) -> object:
        return self._script.pop(0)


class _Acquire:
    def __init__(self, conn: _Conn) -> None:
        self._conn = conn

    async def __aenter__(self) -> _Conn:
        return self._conn

    async def __aexit__(self, *_exc: object) -> None:
        return None


class _Pool:
    def __init__(self, script: list[object]) -> None:
        self._conn = _Conn(script)

    def acquire(self) -> _Acquire:
        return _Acquire(self._conn)


def _context_script() -> list[object]:
    """Rows for _gather_kb_context.

    Order: entries, kb_creates, domains, day thoughts, week consolidation.
    The consolidation fetch has no 24h window; an empty list is "no week yet".
    """
    now = datetime.now(timezone.utc)
    entry = {"title": "t", "domain": "d", "fetched_at": now}
    return [[entry], [], [{"domain": "d", "entry_count": 1}], [], []]


@pytest.mark.asyncio
async def test_generation_failure_fails_the_cycle() -> None:
    """A generation error must yield success=False + error, never 0-success."""
    from gaius.engine.services.cognition_logic import process_cognition_cycle

    result = await process_cognition_cycle(
        db_pool=_Pool(_context_script()),
        payload={"max_thoughts": 3, "trigger": "test"},
        inference_client=_RaisingClient(),
    )
    assert result.success is False
    assert result.error is not None and "timed out" in result.error
    assert result.thoughts_generated == 0


@pytest.mark.asyncio
async def test_context_gather_failure_is_not_an_empty_kb() -> None:
    """DB faults during context gathering surface as CTXGATHER, not quiet."""
    from gaius.engine.services.cognition_logic import _gather_kb_context

    class _BrokenPool:
        def acquire(self):
            raise ConnectionError("db down")

    with pytest.raises(RuntimeError, match="COG.00000036"):
        await _gather_kb_context(_BrokenPool())


class _EmptyTextClient:
    """Full token spend, no answer text — the think-burn shape."""

    async def call(self, *a, **k):
        return {"text": "", "tokens_used": 2048, "latency_ms": 1.0, "model": "m"}


@pytest.mark.asyncio
async def test_week_consolidation_is_carried_into_the_next_prompt() -> None:
    """A consolidation older than the day window is what the next cycle reads."""
    from gaius.engine.services.cognition_logic import _gather_kb_context, _generate_thoughts

    now = datetime.now(timezone.utc)
    week = {
        "title": "The loop echoed",
        "summary": (
            "KNOWN: Restart survival is settled.\n"
            "STOP: Do not ask what survives a restart without a selection rule.\n"
            "OPEN: The selection rule is still open."
        ),
        "content": "WELL_ONLY " + ("investigation " * 80),
        "slice_id": "2026-W39",
    }
    ctx = await _gather_kb_context(
        _Pool(
            [
                [{"title": "t", "domain": "d", "fetched_at": now}],
                [],
                [{"domain": "d", "entry_count": 1}],
                [{"title": "Durable state is the control plane", "summary": "again", "salience": 0.9}],
                [week],
            ]
        )
    )
    assert ctx["week_consolidation"]["slice_id"] == "2026-W39"
    assert ctx["recent_thoughts"][0]["title"] == "Durable state is the control plane"

    captured: dict[str, str] = {}

    class _Client:
        async def call(self, *, service, action, params):
            captured["prompt"] = params["prompt"]
            captured["system"] = params["system_prompt"]
            return {
                "text": (
                    "TYPE: curiosity\nTITLE: After the week\n"
                    "SUMMARY: A question that is not the week again.\nSALIENCE: 0.4"
                ),
                "tokens_used": 12,
                "latency_ms": 1.0,
                "model": "m",
                "job_id": "j",
            }

    await _generate_thoughts(_Client(), ctx, max_thoughts=1, trigger_reason="test")
    assert "WEEK CONSOLIDATION (2026-W39)" in captured["prompt"]
    assert "selection rule" in captured["prompt"]
    assert "WELL_ONLY" not in captured["prompt"]
    assert "do not re-derive" in captured["system"].lower()


@pytest.mark.asyncio
async def test_backfilled_earlier_week_does_not_displace_the_later_iso_week(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Landed time is not the week in force. W38 arriving after W39 stays history."""
    from gaius.engine.services.cognition_logic import _gather_kb_context
    from gaius.engine.services import theta_understanding

    monkeypatch.setattr(theta_understanding, "current_iso_slice", lambda now=None: "2026-W40")
    now = datetime.now(timezone.utc)
    w38 = {
        "title": "Earlier week, later landing",
        "summary": "backfill",
        "content": "STOP_REPEATING: do not treat the backfill as current. " + ("x" * 240),
        "slice_id": "2026-W38",
        "created_at": datetime(2026, 9, 29, 18, 0, tzinfo=timezone.utc),
    }
    w39 = {
        "title": "The loop echoed",
        "summary": "established",
        "content": "STOP_REPEATING: Durable state is the control plane is already known. " + ("x" * 240),
        "slice_id": "2026-W39",
        "created_at": datetime(2026, 9, 29, 1, 31, tzinfo=timezone.utc),
    }
    ctx = await _gather_kb_context(
        _Pool(
            [
                [{"title": "t", "domain": "d", "fetched_at": now}],
                [],
                [{"domain": "d", "entry_count": 1}],
                [],
                [w38, w39],
            ]
        )
    )
    assert ctx["week_consolidation"]["slice_id"] == "2026-W39"
    assert ctx["week_consolidation"]["title"] == "The loop echoed"


@pytest.mark.asyncio
async def test_think_burn_is_loud_not_zero_thoughts() -> None:
    from gaius.engine.services.cognition_logic import process_cognition_cycle

    result = await process_cognition_cycle(
        db_pool=_Pool(_context_script()),
        payload={"max_thoughts": 3, "trigger": "test"},
        inference_client=_EmptyTextClient(),
    )
    assert result.success is False
    assert result.error is not None and "THINKBURN" in result.error
