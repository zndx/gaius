"""Submit this engine's WORKLOAD CATALOGUE to Signals (Scheduler/SyncWorkloads).

The engine is the peer: it submits the whole catalogue (`replace=True`) at
start and every SYNC_INTERVAL_S so Signals can materialise one Airflow DAG per
enabled entry — runs that are Activities asserting the class's YuniKorn
configuration for exactly the run's duration — and catalogue the rest paused.
Local processes never call Signals: they read `/workloads` from this engine.

Fail-open toward the boot (a dark or older Signals never gates it), loud about
outcomes: every sync logs the records' states; an older Signals without the RPC
logs `#CO.0000000B.NOSYNC` once and retries every RETRY_S; any other failure is
`#CO.0000000C.SYNCFAIL` and retries at the normal interval.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from gaius.engine.services import workload_catalog

logger = logging.getLogger(__name__)

GURU_NOSYNC = "#CO.0000000B.NOSYNC"      # Signals predates Scheduler/SyncWorkloads
GURU_SYNCFAIL = "#CO.0000000C.SYNCFAIL"  # sync refused / unreachable (retry next interval)

SYNC_INTERVAL_S = 30 * 60.0
RETRY_S = 300.0
RPC_TIMEOUT_S = 30.0


def _engine_build() -> str:
    try:
        from gaius.engine.services.efficacy_ledger import engine_rev

        return str(engine_rev() or "")
    except Exception:  # noqa: BLE001
        return ""


class WorkloadSync:
    """Periodic Scheduler/SyncWorkloads with the last outcome kept for `/workloads`."""

    def __init__(self, target: str, *, project: str = workload_catalog.PEER, interval_s: float = SYNC_INTERVAL_S):
        self.target = target
        self.project = project
        self.interval_s = float(interval_s)
        self._task: asyncio.Task | None = None
        self.last_sync_ms: int = 0
        self.last_error: str = ""
        self.last_records: list[dict[str, Any]] = []   # {id, kind, dag_id, state, error}
        self.syncs = 0
        self._unimplemented_logged = False

    # ── lifecycle ────────────────────────────────────────────────────────────
    def start(self, loop: asyncio.AbstractEventLoop | None = None) -> asyncio.Task:
        if self._task is None or self._task.done():
            lp = loop or asyncio.get_event_loop()
            self._task = lp.create_task(self._run(), name="workload-sync")
        return self._task

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            self._task = None

    async def _run(self) -> None:
        while True:
            delay = self.interval_s
            try:
                await self.sync_once()
            except _Unimplemented:
                if not self._unimplemented_logged:
                    logger.warning(
                        "%s Signals at %s has no Scheduler/SyncWorkloads — catalogue not submitted; retry every %.0fs",
                        GURU_NOSYNC, self.target, RETRY_S,
                    )
                    self._unimplemented_logged = True
                delay = RETRY_S
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001 — never kill the loop; the interval retries
                self.last_error = str(e)
                logger.warning("%s SyncWorkloads to %s: %s", GURU_SYNCFAIL, self.target, e)
            await asyncio.sleep(delay)

    # ── one submission ───────────────────────────────────────────────────────
    async def sync_once(self) -> list[dict[str, Any]]:
        import grpc

        from gaius.engine.generated.zndx.scheduler.v1 import scheduler_pb2 as spb
        from gaius.engine.generated.zndx.scheduler.v1 import scheduler_pb2_grpc as spb_grpc

        hints = workload_catalog.schedule_hints()
        req = spb.SyncWorkloadsRequest(
            peer=self.project, workloads=hints, replace=True, engine_build=_engine_build()
        )
        channel = grpc.aio.insecure_channel(self.target)
        try:
            stub = spb_grpc.SchedulerStub(channel)
            try:
                resp = await stub.SyncWorkloads(req, timeout=RPC_TIMEOUT_S)
            except grpc.aio.AioRpcError as e:
                if e.code() == grpc.StatusCode.UNIMPLEMENTED:
                    raise _Unimplemented() from e
                raise RuntimeError(f"{e.code().name} {e.details()}") from e
        finally:
            await channel.close()
        if not resp.accepted:
            raise RuntimeError(resp.error or "SyncWorkloads refused")
        records = [
            {
                "id": r.workload.id,
                "kind": r.workload.kind,
                "dag_id": r.dag_id,
                "state": r.state,
                "error": r.error,
            }
            for r in resp.records
        ]
        self.last_records = records
        self.last_sync_ms = int(time.time() * 1000)
        self.last_error = ""
        self.syncs += 1
        self._unimplemented_logged = False
        by_state: dict[str, int] = {}
        for r in records:
            by_state[r["state"] or "?"] = by_state.get(r["state"] or "?", 0) + 1
        logger.info(
            "workload catalogue submitted to %s: %d entr%s → %s",
            self.target, len(hints), "y" if len(hints) == 1 else "ies",
            ", ".join(f"{k}={v}" for k, v in sorted(by_state.items())) or "no records",
        )
        for r in records:
            if r["error"]:
                logger.warning("workload %s (%s): %s — %s", r["id"], r["dag_id"], r["state"], r["error"])
        return records

    # ── view ─────────────────────────────────────────────────────────────────
    def status(self) -> dict[str, Any]:
        return {
            "target": self.target,
            "last_sync_ms": self.last_sync_ms,
            "last_error": self.last_error,
            "syncs": self.syncs,
            "records": list(self.last_records),
        }


class _Unimplemented(Exception):
    pass


# ── singleton ────────────────────────────────────────────────────────────────
_SYNC: WorkloadSync | None = None


def init_workload_sync(target: str, **kw: Any) -> WorkloadSync:
    global _SYNC
    if _SYNC is None:
        _SYNC = WorkloadSync(target, **kw)
    return _SYNC


def get_workload_sync() -> WorkloadSync | None:
    return _SYNC
