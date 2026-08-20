"""Spawned Metaflow children are Yield-able."""

from __future__ import annotations

import asyncio

import pytest

from gaius.engine.flow_processes import (
    FlowProcessTable,
    SpawnedFlow,
    workload_id_for,
)
from gaius.engine.generated.zndx.engine.v1 import engine_pb2 as zpb
from gaius.engine.grpc.servicers.zndx_engine_servicer import GaiusZndxEngineServicer


def test_workload_id_stable():
    assert workload_id_for("article-curate", 12) == "article-curate-12"
    assert workload_id_for("prospects-update", 3) == "prospects-update-3"


@pytest.mark.asyncio
async def test_yield_unknown_is_idempotent():
    table = FlowProcessTable()
    ended, msg = await table.yield_one("missing")
    assert ended is False
    assert "no spawned flow" in msg


@pytest.mark.asyncio
async def test_yield_kills_spawned_child():
    table = FlowProcessTable()
    proc = await asyncio.create_subprocess_exec(
        "python", "-c", "import time; time.sleep(86400)",
    )
    table.register(
        SpawnedFlow(workload_id="article-curate-1", kind="article-curate", proc=proc)
    )
    ended, msg = await table.yield_one("article-curate-1")
    assert ended is True
    assert proc.returncode is not None
    ended2, _ = await table.yield_one("article-curate-1")
    assert ended2 is False


class _Services:
    backend_router = None
    orchestrator_service = None
    config = None


@pytest.mark.asyncio
async def test_zndx_yield_rpc_unknown():
    svc = GaiusZndxEngineServicer(_Services())
    r = await svc.Yield(
        zpb.YieldRequest(workload_id="nope", reason=zpb.YIELD_REASON_PREEMPTED),
        context=None,
    )
    assert r.ok
    assert not r.process_ended


def test_alias_for_workload():
    from gaius.engine.sentinel_yield import alias_for_workload

    assert alias_for_workload("gaius-thinking") == "thinking"
    assert alias_for_workload("thinking") == "thinking"
    assert alias_for_workload("clt-probe-4") == "clt"
    assert alias_for_workload("nope") == ""


class _Orch:
    def __init__(self):
        self.stopped: list[str] = []

    async def stop_endpoint(self, alias: str) -> bool:
        self.stopped.append(alias)
        return True

    async def complete_workload(self, wid: str) -> None:
        return None


@pytest.mark.asyncio
async def test_yield_stops_thinking_endpoint():
    from gaius.engine.sentinel_yield import yield_workload

    orch = _Orch()
    svc = type("S", (), {"orchestrator_service": orch, "ambient_service": None})()
    r = await yield_workload(
        svc,
        zpb.YieldRequest(
            workload_id="gaius-thinking", reason=zpb.YIELD_REASON_PREEMPTED
        ),
    )
    assert r.ok
    assert r.process_ended
    assert orch.stopped == ["thinking"]
