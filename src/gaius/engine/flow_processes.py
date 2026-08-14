"""Registry of spawned Metaflow children for Engine/Yield.

article_curate and prospects_update run as host subprocesses. Yield kills
that child; checkpointed DB/Iceberg state is how they resume.
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import Lock
from typing import Any

log = logging.getLogger("gaius.engine.flow_processes")


@dataclass
class SpawnedFlow:
    workload_id: str
    kind: str
    proc: asyncio.subprocess.Process
    task_id: int | None = None
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def pid(self) -> int | None:
        return self.proc.pid


class FlowProcessTable:
    def __init__(self) -> None:
        self._mu = Lock()
        self._rows: dict[str, SpawnedFlow] = {}

    def register(self, row: SpawnedFlow) -> None:
        with self._mu:
            self._rows[row.workload_id] = row
        log.info(
            "registered flow kind=%s workload_id=%s pid=%s",
            row.kind,
            row.workload_id,
            row.pid,
        )

    def unregister(self, workload_id: str) -> SpawnedFlow | None:
        with self._mu:
            return self._rows.pop(workload_id, None)

    def get(self, workload_id: str) -> SpawnedFlow | None:
        with self._mu:
            return self._rows.get(workload_id)

    def list(self) -> list[SpawnedFlow]:
        with self._mu:
            return list(self._rows.values())

    async def yield_one(self, workload_id: str) -> tuple[bool, str]:
        row = self.unregister(workload_id)
        if row is None:
            return False, f"no spawned flow for workload_id={workload_id or '(empty)'}"
        ended = await _terminate(row.proc)
        msg = (
            f"ended {row.kind} pid={row.pid} workload_id={workload_id}"
            if ended
            else f"{row.kind} pid={row.pid} already gone workload_id={workload_id}"
        )
        log.info("yield %s", msg)
        return ended, msg


_TABLE = FlowProcessTable()


def flow_processes() -> FlowProcessTable:
    return _TABLE


async def _terminate(proc: asyncio.subprocess.Process) -> bool:
    if proc.returncode is not None:
        return True
    try:
        proc.send_signal(signal.SIGTERM)
    except ProcessLookupError:
        return True
    try:
        await asyncio.wait_for(proc.wait(), timeout=8.0)
        return True
    except TimeoutError:
        try:
            proc.kill()
        except ProcessLookupError:
            return True
        await proc.wait()
        return True


def workload_id_for(kind: str, task_id: int) -> str:
    return f"{kind}-{task_id}"
