"""STP must not poison Cognition clocks; bind + skip-unknown."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from gaius.engine.services.cognition_service import CognitionConfig, CognitionService
from gaius.engine.services.scheduled_task_processor import (
    ScheduledTask,
    ScheduledTaskProcessor,
    _dedupe_symbols,
)


def test_dedupe_symbols_keeps_first_seen_order() -> None:
    assert _dedupe_symbols(["MTN", "LLY"], ["LLY", "DIS"], "XOM") == [
        "MTN", "LLY", "DIS", "XOM",
    ]
    assert _dedupe_symbols(["", "  ", "SLB"]) == ["SLB"]
    assert _dedupe_symbols({"CHTR": 1, "XOM": 2}) == ["CHTR", "XOM"]


class _CheckConn:
    def __init__(self, raw: object) -> None:
        self.raw = raw

    async def fetchval(self, sql: str) -> object:
        assert "prospects_check" in sql
        assert "completed_at IS NOT NULL" in sql
        return self.raw

    async def __aenter__(self) -> "_CheckConn":
        return self

    async def __aexit__(self, *_exc: object) -> bool:
        return False


class _CheckPool:
    def __init__(self, raw: object) -> None:
        self.raw = raw

    def acquire(self) -> _CheckConn:
        return _CheckConn(self.raw)


@pytest.mark.asyncio
async def test_update_symbols_come_from_the_latest_check_result() -> None:
    proc = ScheduledTaskProcessor(database_url="postgres://unused")
    proc._pool = _CheckPool('{"symbols": ["MTN", "LLY", "MTN", " "]}')
    assert await proc._symbols_from_latest_check() == ["MTN", "LLY"]
    proc._pool = _CheckPool({"symbols": ["DIS"]})
    assert await proc._symbols_from_latest_check() == ["DIS"]
    proc._pool = _CheckPool(None)
    assert await proc._symbols_from_latest_check() == []
    proc._pool = None
    with pytest.raises(RuntimeError, match="no database pool"):
        await proc._symbols_from_latest_check()


@pytest.mark.asyncio
async def test_unknown_notify_does_not_poison() -> None:
    proc = ScheduledTaskProcessor(database_url="postgres://unused")
    poisoned: list[tuple[int, str]] = []
    executed: list[int] = []

    async def fake_error(task_id: int, error: str) -> None:
        poisoned.append((task_id, error))

    async def fake_exec(task_id: int) -> None:
        executed.append(task_id)

    setattr(proc, "_mark_task_error", fake_error)
    setattr(proc, "_execute_task", fake_exec)
    await proc._process_notification('{"id": 1, "task_type": "feed_check"}')
    assert poisoned == []
    assert executed == []


@pytest.mark.asyncio
async def test_known_notify_executes() -> None:
    proc = ScheduledTaskProcessor(database_url="postgres://unused")
    executed: list[int] = []

    async def fake_exec(task_id: int) -> None:
        executed.append(task_id)

    async def fake_handler(_task: ScheduledTask) -> dict:
        return {}

    proc.register_handler("feature_probe", fake_handler)
    setattr(proc, "_execute_task", fake_exec)
    await proc._process_notification('{"id": 2, "task_type": "feature_probe"}')
    assert executed == [2]


@pytest.mark.asyncio
async def test_pickup_due_only_owned_incomplete() -> None:
    proc = ScheduledTaskProcessor(database_url="postgres://unused")

    async def fake_handler(_task: ScheduledTask) -> dict:
        return {}

    proc.register_handler("feature_probe", fake_handler)
    captured: dict[str, object] = {}

    class FakeConn:
        async def fetch(self, sql: str, *args: object) -> list:
            captured["sql"] = sql
            captured["args"] = args
            return []

    class FakeAcquire:
        async def __aenter__(self) -> FakeConn:
            return FakeConn()

        async def __aexit__(self, *_a: object) -> bool:
            return False

    setattr(proc, "_pool", SimpleNamespace(acquire=lambda: FakeAcquire()))
    await proc._pickup_due()
    sql = str(captured["sql"])
    assert "completed_at IS NULL" in sql
    assert "task_type = ANY" in sql
    assert "SELECT id, task_type" in sql
    assert captured["args"] == (["feature_probe"],)


@pytest.mark.asyncio
async def test_pickup_due_does_not_await_handler() -> None:
    """LuxCore enrich must not stall the listen loop's due tick."""
    proc = ScheduledTaskProcessor(database_url="postgres://unused")

    async def fake_handler(_task: ScheduledTask) -> dict:
        return {}

    proc.register_handler("publish_cards", fake_handler)
    started = asyncio.Event()
    release = asyncio.Event()
    executed: list[int] = []

    async def fake_exec(task_id: int) -> None:
        executed.append(task_id)
        started.set()
        await release.wait()

    setattr(proc, "_execute_task", fake_exec)

    class FakeConn:
        async def fetch(self, sql: str, *args: object) -> list:
            return [{"id": 7, "task_type": "publish_cards"}]

    class FakeAcquire:
        async def __aenter__(self) -> FakeConn:
            return FakeConn()

        async def __aexit__(self, *_a: object) -> bool:
            return False

    setattr(proc, "_pool", SimpleNamespace(acquire=lambda: FakeAcquire()))
    await asyncio.wait_for(proc._pickup_due(), timeout=1)
    await asyncio.wait_for(started.wait(), timeout=1)
    assert executed == [7]
    release.set()


@pytest.mark.asyncio
async def test_pickup_due_skips_singleton_in_flight() -> None:
    proc = ScheduledTaskProcessor(database_url="postgres://unused")

    async def fake_handler(_task: ScheduledTask) -> dict:
        return {}

    proc.register_handler("publish_cards", fake_handler)
    proc._inflight_types.add("publish_cards")
    executed: list[int] = []

    async def fake_exec(task_id: int) -> None:
        executed.append(task_id)

    setattr(proc, "_execute_task", fake_exec)

    class FakeConn:
        async def fetch(self, sql: str, *args: object) -> list:
            return [{"id": 8, "task_type": "publish_cards"}]

    class FakeAcquire:
        async def __aenter__(self) -> FakeConn:
            return FakeConn()

        async def __aexit__(self, *_a: object) -> bool:
            return False

    setattr(proc, "_pool", SimpleNamespace(acquire=lambda: FakeAcquire()))
    await proc._pickup_due()
    await asyncio.sleep(0)
    assert executed == []


def test_bind_cognition_skips_existing_handlers() -> None:
    proc = ScheduledTaskProcessor(database_url="postgres://unused")

    async def existing(_task: ScheduledTask) -> dict:
        return {"owner": "stp"}

    proc.register_handler("article_curate", existing)

    class Cog:
        SUPPORTED_TASK_TYPES = ["feed_check", "article_curate", "heuristic_triage"]

        async def run_claimed_task(self, task_type: str, payload: dict) -> dict:
            return {"ok": task_type, "payload": payload}

    proc.bind_cognition(Cog())
    assert proc._handlers["article_curate"] is existing
    assert "feed_check" in proc._handlers
    assert "heuristic_triage" in proc._handlers


def test_cognition_pickup_types_omit_gpu_when_busy() -> None:
    busy = CognitionService(CognitionConfig(), get_gpu_idle=lambda: False)
    idle = CognitionService(CognitionConfig(), get_gpu_idle=lambda: True)
    busy_types = busy._pickup_types()
    idle_types = idle._pickup_types()
    assert "feed_check" in busy_types
    assert "heuristic_triage" in busy_types
    assert "content_processing" in busy_types
    assert "cognition_cycle" not in busy_types
    assert "llm_triage" not in busy_types
    assert "cognition_cycle" in idle_types
    assert "feed_check" in idle_types


def test_prospects_requests_the_platform_metaflow_profile() -> None:
    """Prospects reads the Signals datastore, so its child cannot run local.

    ProspectsUpdateFlow.start() calls require_signals_metaflow(), which
    fail-fasts on METAFLOW_DEFAULT_DATASTORE=local (#MF.00000006.NOPLATFORM).
    The spawner defaults to local for host ticks, so prospects must opt out
    explicitly or every run exits 1.
    """
    import inspect

    from gaius.engine.services import scheduled_task_processor as stp

    src = inspect.getsource(stp.ScheduledTaskProcessor)
    handler = src[src.index("async def handle_prospects_update") :]
    handler = handler[: handler.index("async def handle_metabase_sync")]
    assert 'metaflow_mode="platform"' in handler

    # And the spawner still defaults to local for everything else.
    sig = inspect.signature(stp.ScheduledTaskProcessor._run_spawned_metaflow)
    assert sig.parameters["metaflow_mode"].default == "local"


def test_airflow_ordered_metaflow_does_not_admit_its_own_sentinel() -> None:
    """Signals already asserted the activity claims. The child records them."""
    import inspect

    from gaius.engine.services import scheduled_task_processor as stp
    from gaius.flows.base import GaiusFlow

    src = inspect.getsource(stp.ScheduledTaskProcessor._run_spawned_metaflow)
    mediated = src[src.index("if mediated:"):src.index("else:")]
    assert "GAIUS_YK_ACTIVITY_ID" in mediated
    assert "bind_workload_id" not in mediated
    assert "apply_and_admit" not in mediated
    legacy = src[src.index("else:"):src.index("create_subprocess_exec")]
    assert "bind_workload_id" in legacy
    assert "apply_and_admit" in legacy
    assert "GAIUS_YK_APPLICATION_ID" in legacy

    claim = inspect.getsource(GaiusFlow._claim_yk)
    early = claim[:claim.index("apply_and_admit")]
    assert "GAIUS_YK_ACTIVITY_ID" in early
    assert "return" in early
    assert 'getattr(self, "gpu_tokens", 0)' in claim


def test_prospects_check_records_symbols_and_the_update_completes_empty() -> None:
    """The check does not insert the update. An empty symbol set is not a skip."""
    import inspect

    from gaius.engine.services import scheduled_task_processor as stp

    src = inspect.getsource(stp.ScheduledTaskProcessor)
    check = src[src.index("async def handle_prospects_check"):src.index("async def handle_prospects_update")]
    assert "_enqueue_prospects_update" not in check
    assert '"symbols": symbols_for_update' in check
    update = src[src.index("async def handle_prospects_update"):src.index("async def handle_metabase_sync")]
    assert "nothing to update" in update
    assert '"skipped"' not in update
    assert 'metaflow_mode="platform"' in update
    assert "_symbols_from_latest_check" in update


def test_spawned_metaflow_defaults_to_local() -> None:
    """@kubernetes steps hang under the platform profile; default stays local."""
    import inspect

    from gaius.engine.services import scheduled_task_processor as stp

    src = inspect.getsource(stp.ScheduledTaskProcessor)
    handler = src[src.index("async def handle_prospects_update") :]
    handler = handler[: handler.index("async def handle_metabase_sync")]
    assert 'metaflow_mode="platform"' in handler
    sig = inspect.signature(stp.ScheduledTaskProcessor._run_spawned_metaflow)
    assert sig.parameters["metaflow_mode"].default == "local"
