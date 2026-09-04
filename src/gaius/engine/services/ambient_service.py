"""Ambient Computing service — scheduled mode.

(2026-09-04) The continuous in-engine cycle is gone: HN fetch → compaction →
cognition synthesis → a synthetic reasoning workload that evicted and
restored endpoints, on a 10–30 s cooldown, inside the engine process. It ran
"invisibly" but never through the scheduler, and its GPU juggling is exactly
what declared resource intents replace. Ambient is now
``AmbientSynthesisFlow`` (gaius.flows.ambient.synthesis_flow) on pg_cron
(``ambient-synthesis``, every 20 min), claimed by the scheduled task
processor as ``ambient_synthesis`` with its own sentinel and phase intents.

This object is the engine-side surface the Ambient* RPCs, the CLI and the
TUI kept:

* operator switch — ``start_daemon`` enables the schedule and queues one run,
  ``stop_daemon`` disables it (the task handler then skips honestly);
* status derived from ``scheduled_tasks`` (cycles, last run, in-flight);
* a read-through view of the durable ambient buffer (``buffer_entries``)
  for Discover token counts, synthesis slices and export;
* ``run_scheduled_cycle`` — queue a run now and stream its progress.

Nothing here calls a model.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any, AsyncIterator, Optional

import asyncpg

from ..generated import gaius_service_pb2 as pb
from .ambient_buffer import BufferEntry
from .buffer_store import DurableBuffer

if TYPE_CHECKING:
    from ..backends import BackendRouter
    from ..config import EngineConfig
    from .agenda_tracker import AgendaTracker
    from .orchestrator_service import OrchestratorService

logger = logging.getLogger(__name__)

TASK_TYPE = "ambient_synthesis"
CRON_JOB = "ambient-synthesis"
SCHEDULE = "*/20 * * * *"
GURU_NOPOOL = "#AMB.00000002.NOPOOL"


def ambient_boot_action(
    state: dict[str, Any] | None,
    *,
    auto_start: bool,
) -> str:
    """Decide boot action. ``skip`` / ``resume`` / ``start``.

    ``resume`` and ``start`` both mean "operator switch on" in scheduled mode;
    they are kept distinct because the persisted state records them so."""
    if not auto_start:
        return "skip"
    if state and state.get("operator_disabled"):
        return "skip"
    if state and state.get("running"):
        return "resume"
    return "start"


class AmbientPhase(Enum):
    """Phases reported on the Ambient status/event surface."""

    BASELINE_HEALTH = "baseline_health"
    BASELINE_WORKLOAD = "baseline_workload"
    FETCH_CONTENT = "fetch_content"
    BUFFER_ANALYSIS = "buffer_analysis"
    SUMMARIZATION = "summarization"
    REASONING_EVICTION = "reasoning_eviction"
    REASONING_WORKLOAD = "reasoning_workload"
    BASELINE_RESTORATION = "baseline_restoration"
    COMPLETE = "complete"
    ERROR = "error"


@dataclass
class CycleResult:
    """Result of one scheduled ambient run (derived from its task row)."""

    success: bool
    phases_completed: int
    total_tasks: int
    successful_tasks: int
    endpoint_latencies: dict[str, int] = field(default_factory=dict)
    error_message: str = ""
    duration_ms: int = 0


_PHASE_BY_PB = {
    pb.AMBIENT_PHASE_BASELINE_HEALTH: AmbientPhase.BASELINE_HEALTH,
    pb.AMBIENT_PHASE_BASELINE_WORKLOAD: AmbientPhase.BASELINE_WORKLOAD,
    pb.AMBIENT_PHASE_FETCH_CONTENT: AmbientPhase.FETCH_CONTENT,
    pb.AMBIENT_PHASE_BUFFER_ANALYSIS: AmbientPhase.BUFFER_ANALYSIS,
    pb.AMBIENT_PHASE_SUMMARIZATION: AmbientPhase.SUMMARIZATION,
    pb.AMBIENT_PHASE_REASONING_EVICTION: AmbientPhase.REASONING_EVICTION,
    pb.AMBIENT_PHASE_REASONING_WORKLOAD: AmbientPhase.REASONING_WORKLOAD,
    pb.AMBIENT_PHASE_BASELINE_RESTORATION: AmbientPhase.BASELINE_RESTORATION,
    pb.AMBIENT_PHASE_COMPLETE: AmbientPhase.COMPLETE,
    pb.AMBIENT_PHASE_ERROR: AmbientPhase.ERROR,
}


def _result_dict(raw: Any) -> dict[str, Any]:
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        v = json.loads(raw)
        return v if isinstance(v, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def cycle_result_from_row(row: dict[str, Any] | None) -> CycleResult | None:
    """A scheduled_tasks row → the CycleResult the status surface reports."""
    if not row:
        return None
    res = _result_dict(row.get("result"))
    status = str(res.get("status") or ("completed" if not row.get("error") else "failed"))
    ok = row.get("error") is None and status == "completed"
    picked, done = row.get("picked_up_at"), row.get("completed_at")
    dur = int((done - picked).total_seconds() * 1000) if picked and done else 0
    msg = row.get("error") or ""
    if not ok and not msg:
        msg = f"{status}: {res.get('reason') or res.get('message') or ''}".strip(": ")
    return CycleResult(
        success=ok,
        phases_completed=3 if ok else 0,
        total_tasks=1,
        successful_tasks=1 if ok else 0,
        error_message=str(msg),
        duration_ms=dur,
    )


class AmbientWorkloadService:
    """Operator surface + read-through view for the scheduled ambient flow."""

    def __init__(
        self,
        config: "EngineConfig",
        orchestrator: "OrchestratorService",
        backend_router: "BackendRouter",
        db_pool: Optional[asyncpg.Pool] = None,
    ):
        self._config = config
        self._orchestrator = orchestrator
        self._backend_router = backend_router
        self._db_pool = db_pool

        self._baseline_endpoints = list(config.startup.preload_endpoints)
        self._reasoning_endpoint = "thinking"

        self._current_phase = AmbientPhase.COMPLETE
        self._event_queue: asyncio.Queue[pb.AmbientPhaseEvent] = asyncio.Queue()
        self._agenda_tracker: Optional["AgendaTracker"] = None
        self._gpu_paused = False
        self._prospects_service: Any | None = None
        self._publishing_buffer: Any | None = None
        self._publishing_axis: Any | None = None

        buffer_cfg = config.ambient_buffer
        self._buffer = DurableBuffer(db_pool, "ambient", buffer_cfg.buffer_max_bytes)

        # Cached schedule view (refreshed by _refresh_status every 30 s and on
        # every operator action); get_status() is sync.
        self._schedule_enabled = False
        self._sched: dict[str, Any] = {}
        self._state: dict[str, Any] = {}
        self._refresh_task: asyncio.Task[None] | None = None
        logger.info(
            "AmbientWorkloadService (scheduled mode: pg_cron %s %s) buffer: %s bytes%s",
            CRON_JOB,
            SCHEDULE,
            buffer_cfg.buffer_max_bytes,
            "" if db_pool is not None else " (no db pool: RAM buffer, no schedule)",
        )

    # ── attachments (synthesis axes are read by the flow, kept for callers) ──
    def attach_prospects(self, prospects: Any) -> None:
        self._prospects_service = prospects

    def attach_publishing(self, buffer: Any) -> None:
        self._publishing_buffer = buffer

    def attach_publishing_axis(self, axis: Any) -> None:
        self._publishing_axis = axis
        self._publishing_buffer = axis.buffer

    def set_agenda_tracker(self, tracker: "AgendaTracker") -> None:
        self._agenda_tracker = tracker
        logger.info("AgendaTracker connected to AmbientWorkloadService")

    # ── status ────────────────────────────────────────────────────────────
    def get_status(self) -> dict[str, Any]:
        s = self._sched
        st = self._state
        last = cycle_result_from_row(s.get("last"))
        in_flight = int(s.get("in_flight") or 0)
        self._ensure_refresh()
        return {
            "mode": "scheduled",
            "schedule": f"pg_cron {CRON_JOB} {SCHEDULE} → task {TASK_TYPE}",
            "cycle_running": in_flight > 0,
            # The flow's product is the thinking synthesis; report that phase
            # while a run is in flight, else complete.
            "current_phase": (
                AmbientPhase.SUMMARIZATION.value if in_flight else AmbientPhase.COMPLETE.value
            ),
            "cycles_completed": int(s.get("completed_ok") or 0),
            "last_cycle_at": _iso(s.get("last", {}).get("completed_at") if s.get("last") else None),
            "baseline_endpoints": self._baseline_endpoints,
            "reasoning_endpoint": self._reasoning_endpoint,
            "gpu_paused": self._gpu_paused,
            "daemon_running": self._schedule_enabled,
            "daemon_cycle": int(s.get("completed_all") or 0),
            "max_cycles": None,
            "total_daemon_tasks": int(s.get("completed_all") or 0),
            "successful_daemon_tasks": int(s.get("completed_ok") or 0),
            "daemon_started_at": _iso(st.get("started_at")),
            "daemon_stopped_at": _iso(st.get("stopped_at")),
            "queued": int(s.get("queued") or 0),
            "operator_disabled": bool(st.get("operator_disabled", False)),
            "preempted": bool(st.get("preempted", False)),
            "buffer": self._buffer.get_stats(),
            "last_result": (
                {
                    "success": last.success,
                    "phases_completed": last.phases_completed,
                    "total_tasks": last.total_tasks,
                    "successful_tasks": last.successful_tasks,
                    "endpoint_latencies": last.endpoint_latencies,
                    "error_message": last.error_message,
                    "duration_ms": last.duration_ms,
                }
                if last
                else None
            ),
        }

    async def _refresh_status(self) -> None:
        if self._db_pool is None:
            return
        async with self._db_pool.acquire() as conn:
            counts = await conn.fetchrow(
                """
                SELECT
                  count(*) FILTER (WHERE completed_at IS NOT NULL AND error IS NULL
                                     AND COALESCE(result->>'status','completed') = 'completed') AS completed_ok,
                  count(*) FILTER (WHERE completed_at IS NOT NULL) AS completed_all,
                  count(*) FILTER (WHERE picked_up_at IS NOT NULL AND completed_at IS NULL) AS in_flight,
                  count(*) FILTER (WHERE picked_up_at IS NULL AND completed_at IS NULL) AS queued
                FROM scheduled_tasks WHERE task_type = $1
                """,
                TASK_TYPE,
            )
            last = await conn.fetchrow(
                "SELECT id, picked_up_at, completed_at, error, result FROM scheduled_tasks "
                "WHERE task_type = $1 AND completed_at IS NOT NULL "
                "ORDER BY completed_at DESC LIMIT 1",
                TASK_TYPE,
            )
            state = await conn.fetchrow(
                "SELECT running, started_at, stopped_at, operator_disabled, preempted "
                "FROM ambient_daemon_state WHERE id = 1"
            )
        self._sched = {**dict(counts), "last": dict(last) if last else None}
        self._state = dict(state) if state else {}
        self._schedule_enabled = bool(self._state) and not bool(self._state.get("operator_disabled"))

    def _ensure_refresh(self) -> None:
        if self._db_pool is None or self._refresh_task is not None:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return

        async def _loop() -> None:
            while True:
                try:
                    await self._refresh_status()
                except Exception as e:  # noqa: BLE001 — surfaced, loop survives
                    logger.warning("ambient status refresh failed: %s", e)
                await asyncio.sleep(30)

        self._refresh_task = loop.create_task(_loop(), name="ambient-status-refresh")
        self._buffer.start_refresh()

    # ── operator switch ───────────────────────────────────────────────────
    async def _enqueue(self, source: str, *, priority: str = "normal") -> tuple[int, bool]:
        """Queue one ambient_synthesis run unless one is already pending/in flight.
        Returns (task_id, freshly_queued)."""
        assert self._db_pool is not None
        async with self._db_pool.acquire() as conn:
            existing = await conn.fetchval(
                "SELECT id FROM scheduled_tasks WHERE task_type = $1 AND completed_at IS NULL "
                "ORDER BY id LIMIT 1",
                TASK_TYPE,
            )
            if existing is not None:
                return int(existing), False
            tid = await conn.fetchval(
                "INSERT INTO scheduled_tasks (task_type, payload, priority, source) "
                "VALUES ($1, '{}', $2, $3) RETURNING id",
                TASK_TYPE,
                priority,
                source,
            )
        return int(tid), True

    async def start_daemon(
        self,
        baseline_only: bool = False,
        max_cycles: Optional[int] = None,
    ) -> dict[str, Any]:
        """Operator ON: enable the schedule and queue one run now."""
        if self._db_pool is None:
            return {
                "success": False,
                "message": f"{GURU_NOPOOL} ambient schedule needs the database pool",
            }
        await self._set_operator_disabled(False)
        await self._set_preempted(False)
        self._gpu_paused = False
        await self._persist_daemon_state(running=True)
        tid, fresh = await self._enqueue("ambient_start")
        await self._refresh_status()
        self._ensure_refresh()
        msg = (
            f"ambient synthesis enabled (pg_cron {CRON_JOB} {SCHEDULE}); "
            f"run {'queued' if fresh else 'already pending'} as task {tid}"
        )
        self._emit_event(pb.AMBIENT_PHASE_FETCH_CONTENT, msg, 0.0, {"task_id": str(tid)})
        logger.info(msg)
        return {"success": True, "message": msg, "max_cycles": 0}

    async def stop_daemon(self) -> dict[str, Any]:
        """Operator OFF: scheduled runs skip until start_daemon."""
        if self._db_pool is None:
            return {"success": False, "message": f"{GURU_NOPOOL} no database pool"}
        await self._set_operator_disabled(True)
        await self._persist_daemon_state(running=False)
        await self._refresh_status()
        n = int(self._sched.get("completed_ok") or 0)
        msg = f"ambient synthesis disabled — scheduled runs skip until /ambient start ({n} cycles completed)"
        self._emit_event(pb.AMBIENT_PHASE_COMPLETE, msg, 1.0)
        logger.info(msg)
        return {"success": True, "message": msg, "cycles_completed": n}

    async def ensure_started_on_boot(self) -> dict[str, Any]:
        """Boot: honour the operator switch; the schedule itself is pg_cron's."""
        auto_start = self._config.startup.auto_start_ambient
        state = await self.load_persisted_state()
        action = ambient_boot_action(state, auto_start=auto_start)
        self._ensure_refresh()
        if action == "skip":
            await self._refresh_status()
            return {
                "status": "skipped",
                "message": "auto-start off or operator-disabled (scheduled runs skip)",
            }
        await self._set_operator_disabled(False)
        await self._persist_daemon_state(running=True)
        await self._refresh_status()
        return {
            "status": "scheduled",
            "message": f"ambient synthesis runs on pg_cron {CRON_JOB} ({SCHEDULE}); operator switch on ({action})",
        }

    # ── a run now, streamed ───────────────────────────────────────────────
    async def run_scheduled_cycle(self, baseline_only: bool = False) -> AsyncIterator[pb.AmbientPhaseEvent]:
        """Queue one run at high priority and stream its progress until it
        completes. No deadline: progress is what is watched (the flow's own
        idle net lives in the processor)."""
        if self._db_pool is None:
            yield self._event(pb.AMBIENT_PHASE_ERROR, f"{GURU_NOPOOL} no database pool", 0.0)
            return
        await self._refresh_status()
        if self._state.get("operator_disabled"):
            yield self._event(
                pb.AMBIENT_PHASE_ERROR,
                "ambient synthesis is operator-disabled.\n  Try: /ambient start",
                0.0,
            )
            return
        tid, fresh = await self._enqueue("ambient_cycle", priority="high")
        yield self._emit_event(
            pb.AMBIENT_PHASE_FETCH_CONTENT,
            f"{TASK_TYPE} task {tid} {'queued' if fresh else 'already pending'}; "
            "the processor spawns AmbientSynthesisFlow (fetch → compact → synthesize)",
            0.05,
            {"task_id": str(tid)},
        )
        t0 = time.monotonic()
        running_reported = False
        last_tick = t0
        while True:
            await asyncio.sleep(10)
            row = await self._task_row(tid)
            if row is None:
                yield self._emit_event(pb.AMBIENT_PHASE_ERROR, f"task {tid} vanished", 0.0)
                return
            if row["completed_at"] is not None:
                break
            now = time.monotonic()
            if row["picked_up_at"] is not None and not running_reported:
                running_reported = True
                yield self._emit_event(
                    pb.AMBIENT_PHASE_SUMMARIZATION,
                    f"task {tid} running (flow spawned {int(now - t0)}s after queueing)",
                    0.5,
                    {"task_id": str(tid)},
                )
                last_tick = now
            elif now - last_tick >= 60:
                last_tick = now
                phase = pb.AMBIENT_PHASE_SUMMARIZATION if running_reported else pb.AMBIENT_PHASE_FETCH_CONTENT
                yield self._emit_event(
                    phase,
                    f"task {tid} {'running' if running_reported else 'queued'} for {int(now - t0)}s",
                    0.5 if running_reported else 0.05,
                    {"task_id": str(tid)},
                )
        await self._refresh_status()
        cr = cycle_result_from_row(row)
        res = _result_dict(row.get("result"))
        if cr is not None and cr.success:
            yield self._emit_event(
                pb.AMBIENT_PHASE_COMPLETE,
                f"task {tid} completed in {cr.duration_ms // 1000}s: "
                f"{json.dumps({k: res.get(k) for k in ('status', 'run_id', 'flow') if k in res})}",
                1.0,
                {"task_id": str(tid), "duration_ms": str(cr.duration_ms)},
            )
        else:
            yield self._emit_event(
                pb.AMBIENT_PHASE_ERROR,
                f"task {tid}: {cr.error_message if cr else 'no result'}",
                0.0,
                {"task_id": str(tid)},
            )

    async def _task_row(self, tid: int) -> dict[str, Any] | None:
        assert self._db_pool is not None
        async with self._db_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT id, picked_up_at, completed_at, error, result FROM scheduled_tasks WHERE id = $1",
                tid,
            )
        return dict(row) if row else None

    # ── events ────────────────────────────────────────────────────────────
    def _event(
        self,
        phase: "pb.AmbientPhase",
        message: str,
        progress: float,
        metrics: Optional[dict[str, str]] = None,
    ) -> pb.AmbientPhaseEvent:
        event = pb.AmbientPhaseEvent(
            phase=phase,
            message=message,
            progress=progress,
            timestamp_ms=int(time.time() * 1000),
        )
        for k, v in (metrics or {}).items():
            event.metrics[k] = v
        return event

    def _emit_event(
        self,
        phase: "pb.AmbientPhase",
        message: str,
        progress: float,
        metrics: Optional[dict[str, str]] = None,
    ) -> pb.AmbientPhaseEvent:
        """Push to subscribers (TUI InfoPanel) and return the event."""
        self._current_phase = _PHASE_BY_PB.get(phase, AmbientPhase.COMPLETE)
        event = self._event(phase, message, progress, metrics)
        try:
            self._event_queue.put_nowait(event)
        except asyncio.QueueFull:
            try:
                self._event_queue.get_nowait()
                self._event_queue.put_nowait(event)
            except asyncio.QueueEmpty:
                pass
        return event

    async def subscribe_events(self) -> AsyncIterator[pb.AmbientPhaseEvent]:
        """Stream operator/run events while the schedule is enabled."""
        while self._schedule_enabled or not self._event_queue.empty():
            try:
                event = await asyncio.wait_for(self._event_queue.get(), timeout=1.0)
                yield event
            except asyncio.TimeoutError:
                if not self._schedule_enabled and self._event_queue.empty():
                    break
                continue
            except asyncio.CancelledError:
                break

    # ── persistence (ambient_daemon_state) ────────────────────────────────
    async def _persist_daemon_state(self, running: bool) -> None:
        if not self._db_pool:
            return
        try:
            async with self._db_pool.acquire() as conn:
                await conn.execute(
                    "SELECT update_ambient_daemon_state($1, $2, $3, $4, $5, $6)",
                    running,
                    False,
                    None,
                    int(self._sched.get("completed_all") or 0),
                    int(self._sched.get("completed_all") or 0),
                    int(self._sched.get("completed_ok") or 0),
                )
        except Exception as e:  # noqa: BLE001
            logger.warning("Failed to persist ambient state: %s", e)

    async def _set_operator_disabled(self, disabled: bool) -> None:
        if not self._db_pool:
            return
        try:
            async with self._db_pool.acquire() as conn:
                await conn.execute(
                    "UPDATE ambient_daemon_state SET operator_disabled = $1, "
                    "updated_at = NOW() WHERE id = 1",
                    disabled,
                )
        except Exception as e:  # noqa: BLE001
            logger.warning("set operator_disabled failed: %s", e)

    async def _set_preempted(self, preempted: bool) -> None:
        if not self._db_pool:
            return
        try:
            async with self._db_pool.acquire() as conn:
                await conn.execute(
                    "UPDATE ambient_daemon_state SET preempted = $1, "
                    "updated_at = NOW() WHERE id = 1",
                    preempted,
                )
        except Exception as e:  # noqa: BLE001
            logger.warning("set preempted failed: %s", e)

    async def pause_gpu(self, reason: str = "yield") -> None:
        """A Yield of the legacy standing id: record it; the buffer is durable."""
        self._gpu_paused = True
        await self._set_preempted(True)
        logger.info("Ambient preempt recorded (%s); buffer retained", reason)

    async def resume_gpu(self) -> None:
        self._gpu_paused = False
        await self._set_preempted(False)
        logger.info("Ambient preempt cleared")

    async def load_persisted_state(self) -> Optional[dict[str, Any]]:
        if not self._db_pool:
            return None
        try:
            async with self._db_pool.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    SELECT running, baseline_only, max_cycles, cycles_completed,
                           total_tasks, successful_tasks, started_at, stopped_at,
                           updated_at, operator_disabled, preempted
                    FROM ambient_daemon_state
                    WHERE id = 1
                    """
                )
                return dict(row) if row else None
        except Exception as e:  # noqa: BLE001
            logger.warning("Failed to load persisted state: %s", e)
            return None

    # ── buffer export ─────────────────────────────────────────────────────
    async def export_buffer(self, kb_root: str = "build/dev") -> dict[str, Any]:
        """Write the live ambient buffer to {kb_root}/scratch/{date}/{HHMMSS}_buffer.md."""
        entries = await self._buffer.snapshot()
        stats = self._buffer.get_stats()
        if not entries:
            return {"path": "", "entry_count": 0, "total_bytes": 0, "error": "Buffer empty"}
        content = self._format_buffer_markdown(entries, stats)
        now = datetime.now()
        rel_path = f"scratch/{now.strftime('%Y-%m-%d')}/{now.strftime('%H%M%S')}_buffer.md"
        full_path = Path(kb_root) / rel_path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(content, encoding="utf-8")
        logger.info("Exported buffer to %s: %d entries, %d bytes", rel_path, len(entries), stats["current_bytes"])
        return {"path": rel_path, "entry_count": len(entries), "total_bytes": stats["current_bytes"]}

    def _format_buffer_markdown(self, entries: list[BufferEntry], stats: dict[str, Any]) -> str:
        now = datetime.now()
        lines = [
            "---",
            f"date: {now.isoformat()}",
            "type: buffer-export",
            f"entries: {len(entries)}",
            f"bytes: {stats['current_bytes']}",
            "---",
            "",
            "# Ambient Buffer Export",
            "",
            f"**Exported:** {now.strftime('%Y-%m-%d %H:%M:%S')}",
            f"**Entries:** {len(entries)}",
            f"**Size:** {stats['current_bytes']:,} / {stats['max_bytes']:,} bytes",
            f"**Utilization:** {stats['utilization']:.1%}",
            "",
        ]
        by_role: dict[str, list[BufferEntry]] = defaultdict(list)
        for entry in entries:
            by_role[entry.role.value].append(entry)
        for role, role_entries in by_role.items():
            lines.append(f"## {role.title()} ({len(role_entries)} entries)")
            lines.append("")
            for entry in role_entries:
                meta = entry.metadata or {}
                author = meta.get("author", "")
                story_title = meta.get("story_title", "")
                if author and story_title:
                    lines.append(f"### [{author}] on: {story_title}")
                elif author:
                    lines.append(f"### [{author}]")
                else:
                    lines.append(f"### Entry: {entry.id[:8]}")
                lines.append(f"- **Created:** {entry.created_at.strftime('%H:%M:%S')}")
                if author:
                    lines.append(f"- **Author:** {author}")
                if story_title:
                    lines.append(f"- **Story:** {story_title}")
                if entry.source_url:
                    lines.append(f"- **Link:** {entry.source_url}")
                lines.append("")
                lines.append(entry.content)
                lines.append("")
                lines.append("---")
                lines.append("")
        return "\n".join(lines)


def _iso(v: Any) -> str | None:
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.isoformat()
    return str(v)
