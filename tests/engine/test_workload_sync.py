"""Scheduler/SyncWorkloads submission: shape of the request, the recorded
outcome, and the two failure modes (older Signals; refused)."""

from __future__ import annotations

import asyncio

import grpc
import pytest

from gaius.engine.generated.zndx.scheduler.v1 import scheduler_pb2 as spb
from gaius.engine.generated.zndx.scheduler.v1 import scheduler_pb2_grpc as spbg
from gaius.engine.services import workload_catalog as wc
from gaius.engine.services import workload_sync as ws


class _Signals(spbg.SchedulerServicer):
    def __init__(self, *, accept=True, states=None):
        self.requests: list = []
        self.accept = accept
        self.states = states or {}

    async def SyncWorkloads(self, request, context):
        self.requests.append(request)
        if not self.accept:
            return spb.SyncWorkloadsResponse(accepted=False, error="#CO.00000001.UNKNOWNPEER refused")
        resp = spb.SyncWorkloadsResponse(accepted=True)
        for h in request.workloads:
            resp.records.append(
                spb.WorkloadRecord(
                    workload=h,
                    peer=request.peer,
                    dag_id=h.airflow_dag_id,
                    state=self.states.get(h.id, "materialized" if h.enabled else "paused"),
                )
            )
        return resp


async def _serve(servicer):
    server = grpc.aio.server()
    spbg.add_SchedulerServicer_to_server(servicer, server)
    port = server.add_insecure_port("127.0.0.1:0")
    await server.start()
    return server, f"127.0.0.1:{port}"


def test_sync_submits_the_whole_catalogue_as_a_replace():
    async def run():
        sig = _Signals()
        server, addr = await _serve(sig)
        try:
            sync = ws.WorkloadSync(addr)
            records = await sync.sync_once()
        finally:
            await server.stop(0)
        return sig, sync, records

    sig, sync, records = asyncio.run(run())
    assert len(sig.requests) == 1
    req = sig.requests[0]
    assert req.peer == "gaius" and req.replace is True
    assert len(req.workloads) == len(wc.entries())
    by_id = {h.id: h for h in req.workloads}
    assert by_id["task.article_curate"].enabled and by_id["task.article_curate"].claims[0].gpu == 1
    assert list(by_id["task.clt_skos_label"].after) == ["task.clt_skos_admit"]
    # outcome kept for /workloads
    assert sync.syncs == 1 and sync.last_error == "" and sync.last_sync_ms > 0
    states = {r["id"]: r["state"] for r in records}
    assert states["task.article_curate"] == "materialized"
    assert states["task.fmp_roll"] == "paused"
    assert sync.status()["records"] == records


def test_refused_sync_is_an_error_kept_for_the_view():
    async def run():
        server, addr = await _serve(_Signals(accept=False))
        try:
            sync = ws.WorkloadSync(addr)
            with pytest.raises(RuntimeError, match="refused"):
                await sync.sync_once()
        finally:
            await server.stop(0)

    asyncio.run(run())


def test_older_signals_without_the_rpc_is_unimplemented():
    async def run():
        server, addr = await _serve(spbg.SchedulerServicer())  # base class: UNIMPLEMENTED
        try:
            sync = ws.WorkloadSync(addr)
            with pytest.raises(ws._Unimplemented):
                await sync.sync_once()
        finally:
            await server.stop(0)

    asyncio.run(run())


def test_run_loop_survives_a_dark_signals_and_keeps_going():
    async def run():
        sync = ws.WorkloadSync("127.0.0.1:1", interval_s=0.05)
        task = sync.start(asyncio.get_running_loop())
        await asyncio.sleep(0.3)
        await sync.stop()
        return sync, task

    sync, task = asyncio.run(run())
    assert task.cancelled() or task.done()
    assert sync.syncs == 0 and sync.last_error  # tried, failed loudly, kept looping
