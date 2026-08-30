"""Ambient Computing Workload Service.

Manages ambient computing workload cycles that deliver continuous,
invisible, self-sustaining model activity. The system:

1. Maintains thinking as infrastructure for Cognition+Theta
2. Health is cognition synthesis (Publishing + Prospects + Ambient), not toy Completes
3. Evicts baseline endpoints when reasoning tasks arrive
4. Restores baseline after reasoning completes

Ambient Computing Principles:
- Invisible: Runs via pg_cron without user intervention
- Context-Aware: Respects GPU idle state, endpoint health
- Adaptive: Evicts/restores based on workload demands
- Self-Healing: Integrates with health observer for failures
- Observable: Streaming events, metrics recorded
"""

from __future__ import annotations

import asyncio
import logging
import os
import random
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any, AsyncIterator, Optional

import asyncpg

from ..backends import ProcessStatus
from ..generated import gaius_service_pb2 as pb
from ..metrics import record_exception_caught
from .ambient_buffer import AmbientBuffer, BufferEntry, BufferRole

if TYPE_CHECKING:
    from ..backends import BackendRouter
    from ..config import EngineConfig
    from .agenda_tracker import AgendaTracker
    from .orchestrator_service import OrchestratorService

logger = logging.getLogger(__name__)


def ambient_boot_action(
    state: dict[str, Any] | None,
    *,
    auto_start: bool,
) -> str:
    """Decide boot action. ``skip`` / ``resume`` / ``start``."""
    if not auto_start:
        return "skip"
    if state and state.get("operator_disabled"):
        return "skip"
    if state and state.get("running"):
        return "resume"
    return "start"


class AmbientPhase(Enum):
    """Phases of an ambient computing cycle."""

    BASELINE_HEALTH = "baseline_health"
    BASELINE_WORKLOAD = "baseline_workload"
    FETCH_CONTENT = "fetch_content"  # New: fetch external content
    BUFFER_ANALYSIS = "buffer_analysis"  # New: Bytez analysis of new content
    SUMMARIZATION = "summarization"  # New: summarize fetched content
    REASONING_EVICTION = "reasoning_eviction"
    REASONING_WORKLOAD = "reasoning_workload"
    BASELINE_RESTORATION = "baseline_restoration"
    COMPLETE = "complete"
    ERROR = "error"


@dataclass
class AmbientTask:
    """A standard task for ambient workload testing."""

    endpoint: str
    prompt: str
    expected_capability: str  # "routing", "generation", "coding", "reasoning"
    timeout_secs: int = 30
    system_prompt: str = ""


@dataclass
class TaskResult:
    """Result of executing an ambient task."""

    endpoint: str
    success: bool
    latency_ms: int
    response_length: int = 0
    error: str = ""


@dataclass
class CycleResult:
    """Result of a complete ambient cycle."""

    success: bool
    phases_completed: int
    total_tasks: int
    successful_tasks: int
    endpoint_latencies: dict[str, int] = field(default_factory=dict)
    error_message: str = ""
    duration_ms: int = 0


DEFAULT_REASONING_TASK = AmbientTask(
    endpoint="reasoning",
    prompt="Analyze the trade-offs between microservices and monoliths for a startup.",
    expected_capability="reasoning",
    timeout_secs=120,
)

VARIED_REASONING_PROMPTS: list[str] = [
    "Analyze the trade-offs between microservices and monoliths for a startup.",
    "Compare REST vs GraphQL for a mobile app backend.",
    "Evaluate pros and cons of event sourcing for an e-commerce system.",
    "When should you use a message queue vs direct API calls?",
    "Discuss trade-offs between SQL and NoSQL for a social media platform.",
    "Analyze the CAP theorem implications for a globally distributed system.",
]


class AmbientWorkloadService:
    """Manages ambient computing workload cycles.

    Provides continuous background model activity through multi-phase
    cycles that test baseline endpoints and optionally exercise the
    reasoning endpoint with eviction/restoration.
    """

    def __init__(
        self,
        config: "EngineConfig",
        orchestrator: "OrchestratorService",
        backend_router: "BackendRouter",
        db_pool: Optional[asyncpg.Pool] = None,
    ):
        """Initialize ambient workload service.

        Args:
            config: Engine configuration
            orchestrator: Orchestrator service for endpoint management
            backend_router: Backend router for inference requests
            db_pool: Database pool for state persistence (enables auto-resume)
        """
        self._config = config
        self._orchestrator = orchestrator
        self._backend_router = backend_router
        self._db_pool = db_pool

        # Get baseline endpoints from config
        self._baseline_endpoints = list(config.startup.preload_endpoints)
        self._reasoning_endpoint = "reasoning"

        # Cycle state
        self._cycle_running = False
        self._current_phase = AmbientPhase.COMPLETE
        self._cycles_completed = 0
        self._last_cycle_at: Optional[datetime] = None
        self._last_result: Optional[CycleResult] = None

        # Daemon state for continuous cycling
        self._daemon_running = False
        self._stop_requested = False
        self._max_cycles: Optional[int] = None  # None = infinite
        self._daemon_cycle: int = 0  # Current cycle in daemon mode
        self._daemon_task: Optional[asyncio.Task[None]] = None
        self._event_queue: asyncio.Queue[pb.AmbientPhaseEvent] = asyncio.Queue()
        self._total_daemon_tasks: int = 0
        self._successful_daemon_tasks: int = 0
        self._daemon_started_at: Optional[datetime] = None
        self._daemon_stopped_at: Optional[datetime] = None

        # AgendaTracker integration for incident tracking
        self._agenda_tracker: Optional["AgendaTracker"] = None
        self._current_workload_id: Optional[str] = None
        self._evicted_endpoints: list[str] = []
        self._gpu_paused = False
        self._prospects_service: Any | None = None
        self._publishing_buffer: Any | None = None
        self._publishing_axis: Any | None = None
        from gaius.engine.services.axis_admit import AdmitStats

        self._admit_stats = AdmitStats()

        # Ambient buffer for content fetching (byte-sized FIFO)
        # Fetch and summarize are ALWAYS enabled - this is core ambient work
        buffer_cfg = config.ambient_buffer
        self._buffer = AmbientBuffer(max_bytes=buffer_cfg.buffer_max_bytes)
        logger.info(
            f"AmbientWorkloadService initialized with baseline: {self._baseline_endpoints}, "
            f"buffer: {buffer_cfg.buffer_max_bytes} bytes"
        )

    def attach_prospects(self, prospects: Any) -> None:
        """FMP/prospects FIFO for cognition synthesis (not X bookmarks)."""
        self._prospects_service = prospects

    def attach_publishing(self, buffer: Any) -> None:
        """Independent Publishing axis buffer (cards + arxiv/biorxiv)."""
        self._publishing_buffer = buffer

    def attach_publishing_axis(self, axis: Any) -> None:
        """Publishing axis (ingest + buffer). Synthesis reads the buffer."""
        self._publishing_axis = axis
        self._publishing_buffer = axis.buffer

    def set_agenda_tracker(self, tracker: "AgendaTracker") -> None:
        """Set the agenda tracker for incident tracking.

        Args:
            tracker: AgendaTracker instance for recording phase events
        """
        self._agenda_tracker = tracker
        logger.info("AgendaTracker connected to AmbientWorkloadService")

    # ─────────────────────────────────────────────────────────────────────────
    # Status
    # ─────────────────────────────────────────────────────────────────────────

    def get_status(self) -> dict[str, Any]:
        """Get current ambient service status."""
        return {
            "cycle_running": self._cycle_running,
            "current_phase": self._current_phase.value,
            "cycles_completed": self._cycles_completed,
            "last_cycle_at": (
                self._last_cycle_at.isoformat() if self._last_cycle_at else None
            ),
            "baseline_endpoints": self._baseline_endpoints,
            "reasoning_endpoint": self._reasoning_endpoint,
            # Daemon state
            "gpu_paused": self._gpu_paused,
            "daemon_running": self._daemon_running,
            "daemon_cycle": self._daemon_cycle,
            "max_cycles": self._max_cycles,
            "total_daemon_tasks": self._total_daemon_tasks,
            "successful_daemon_tasks": self._successful_daemon_tasks,
            "daemon_started_at": (
                self._daemon_started_at.isoformat() if self._daemon_started_at else None
            ),
            "daemon_stopped_at": (
                self._daemon_stopped_at.isoformat() if self._daemon_stopped_at else None
            ),
            # Buffer state (fetch/summarize always enabled)
            "buffer": self._buffer.get_stats(),
            "last_result": (
                {
                    "success": self._last_result.success,
                    "phases_completed": self._last_result.phases_completed,
                    "total_tasks": self._last_result.total_tasks,
                    "successful_tasks": self._last_result.successful_tasks,
                    "endpoint_latencies": self._last_result.endpoint_latencies,
                    "error_message": self._last_result.error_message,
                    "duration_ms": self._last_result.duration_ms,
                }
                if self._last_result
                else None
            ),
        }

    # ─────────────────────────────────────────────────────────────────────────
    # Daemon Mode (Start/Stop)
    # ─────────────────────────────────────────────────────────────────────────

    async def start_daemon(
        self,
        baseline_only: bool = False,
        max_cycles: Optional[int] = None,
    ) -> dict[str, Any]:
        """Start continuous ambient cycling in background.

        Returns immediately. Events are pushed to internal queue
        and can be consumed via subscribe_events().

        Args:
            baseline_only: If True, skip reasoning phases
            max_cycles: Run exactly N cycles then stop (None = infinite)

        Returns:
            Dict with success status and message
        """
        if self._daemon_running:
            return {
                "success": False,
                "message": "Already running",
                "max_cycles": self._max_cycles,
            }

        from gaius.engine.sentinel_claim import (
            AMBIENT_WORKLOAD_ID,
            YkAdmitError,
            apply_and_admit,
            bind_workload_id,
        )

        try:
            wid = bind_workload_id("ambient", AMBIENT_WORKLOAD_ID)
            await asyncio.to_thread(apply_and_admit, wid, "ambient")  # off-loop
        except YkAdmitError as e:
            return {
                "success": False,
                "message": str(e),
                "max_cycles": max_cycles,
            }

        await self._set_operator_disabled(False)
        await self._set_preempted(False)
        self._gpu_paused = False
        self._daemon_running = True
        self._stop_requested = False
        self._max_cycles = max_cycles
        self._daemon_cycle = 0
        self._total_daemon_tasks = 0
        self._successful_daemon_tasks = 0
        self._daemon_started_at = datetime.now()
        self._daemon_stopped_at = None  # Clear previous stop time

        # Clear any stale events from queue
        while not self._event_queue.empty():
            try:
                self._event_queue.get_nowait()
            except asyncio.QueueEmpty:
                break

        # HN FIFO must roll even while thinking Complete is slow or unhealthy.
        asyncio.create_task(self._prime_hn_buffer(), name="hn-buffer-prime")

        # Launch background task
        self._daemon_task = asyncio.create_task(
            self._daemon_loop(baseline_only),
            name="ambient-daemon",
        )

        # Persist state for auto-restart after engine restart
        await self._persist_daemon_state(running=True)

        msg = "Started" if max_cycles is None else f"Started ({max_cycles} cycles)"
        logger.info(f"Ambient daemon started: baseline_only={baseline_only}, max_cycles={max_cycles}")

        return {
            "success": True,
            "message": msg,
            "max_cycles": max_cycles,
        }

    async def stop_daemon(self) -> dict[str, Any]:
        """Request graceful stop and return summary.

        Returns:
            Dict with cycle count and summary
        """
        if not self._daemon_running:
            return {
                "success": False,
                "message": "Not running",
                "cycles_completed": 0,
            }

        self._stop_requested = True
        logger.info("Ambient daemon stop requested")

        # Wait briefly for clean shutdown
        for _ in range(10):  # Wait up to 1 second
            if not self._daemon_running:
                break
            await asyncio.sleep(0.1)

        success_rate = (
            f"{self._successful_daemon_tasks}/{self._total_daemon_tasks}"
            if self._total_daemon_tasks > 0
            else "0/0"
        )

        # Persist stopped state (clears running flag)
        await self._persist_daemon_state(running=False)
        await self._set_operator_disabled(True)
        await self._set_preempted(False)

        from gaius.engine.sentinel_claim import release_kind

        release_kind("ambient")

        return {
            "success": True,
            "message": f"Stopped after {self._daemon_cycle} cycles ({success_rate} tasks)",
            "cycles_completed": self._daemon_cycle,
            "total_tasks": self._total_daemon_tasks,
            "successful_tasks": self._successful_daemon_tasks,
        }

    async def _daemon_loop(self, baseline_only: bool) -> None:
        """Background loop that runs cycles continuously."""
        try:
            while not self._stop_requested:
                self._daemon_cycle += 1

                # Check cycle limit
                if self._max_cycles and self._daemon_cycle > self._max_cycles:
                    break

                self._emit_event(
                    pb.AMBIENT_PHASE_BASELINE_HEALTH,
                    f"Cycle {self._daemon_cycle}" + (
                        f" of {self._max_cycles}" if self._max_cycles else ""
                    ),
                    0.0,
                    {"cycle": str(self._daemon_cycle)},
                )

                # Run one cycle with varied tasks
                async for event in self._run_varied_cycle(baseline_only):
                    self._emit_event(
                        event.phase,
                        event.message,
                        event.progress,
                        dict(event.metrics) if event.metrics else None,
                    )
                    if self._stop_requested:
                        break

                if self._stop_requested:
                    break

                # Cycle completed successfully - increment counter
                self._cycles_completed += 1

                # Persist progress after each cycle for crash recovery
                await self._increment_cycle_in_db(
                    tasks_in_cycle=0,  # Already tracked in _run_varied_cycle
                    successful=0,
                )

                # Check if we've hit the limit
                if self._max_cycles and self._daemon_cycle >= self._max_cycles:
                    break

                # Random cooldown between cycles
                cooldown = random.randint(10, 30)
                self._emit_event(
                    pb.AMBIENT_PHASE_COMPLETE,
                    f"Next cycle in {cooldown}s",
                    1.0,
                    {"cooldown_s": str(cooldown)},
                )

                # Interruptible sleep
                for _ in range(cooldown):
                    if self._stop_requested:
                        break
                    await asyncio.sleep(1)

        except asyncio.CancelledError:
            logger.info("Ambient daemon cancelled")
        except Exception as e:
            logger.exception("Ambient daemon error")
            self._emit_event(pb.AMBIENT_PHASE_ERROR, str(e), 0.0)
        finally:
            self._daemon_running = False
            self._daemon_stopped_at = datetime.now()
            success_rate = (
                f"{self._successful_daemon_tasks}/{self._total_daemon_tasks}"
                if self._total_daemon_tasks > 0
                else "0/0"
            )
            self._emit_event(
                pb.AMBIENT_PHASE_COMPLETE,
                f"Completed {self._daemon_cycle} cycles ({success_rate} tasks)",
                1.0,
                {
                    "cycles": str(self._daemon_cycle),
                    "tasks": str(self._total_daemon_tasks),
                    "success_rate": success_rate,
                },
            )
            logger.info(f"Ambient daemon stopped: {self._daemon_cycle} cycles, {success_rate} tasks")

    async def _prime_hn_buffer(self) -> None:
        """Fill the HN FIFO without waiting on thinking Complete."""
        result = await self._fetch_content()
        if not result.get("success"):
            logger.error(
                "HN buffer prime failed.\n"
                "  Guru: #AMB.00000012.HNPRIME\n"
                "  %s",
                result.get("error", "unknown"),
            )
            return
        bytes_added = int(result.get("bytes_added") or 0)
        if bytes_added <= 0:
            logger.error(
                "HN buffer prime wrote 0 bytes.\n"
                "  Guru: #AMB.00000013.HNEMPTY\n"
                "  Try: /ambient status"
            )
            return
        logger.info(
            "HN buffer primed items=%s bytes=%s",
            result.get("items_fetched"),
            bytes_added,
        )
        try:
            await self._buffer.compact_if_needed(self._summarize_compaction)
        except Exception as e:
            logger.error("HN buffer compaction failed.\n  %s", e)

    async def _run_varied_cycle(self, baseline_only: bool) -> AsyncIterator[pb.AmbientPhaseEvent]:
        """Run a single cycle with varied task selection.

        Unlike run_cycle(), this selects random tasks from the varied pools.
        HN fetch is first and does not wait on thinking Complete.
        """
        start_time = time.time()

        # Phase 0: Fetch Content (ALWAYS — core ambient work; not gated on GPU)
        yield self._make_event(
            pb.AMBIENT_PHASE_FETCH_CONTENT,
            "Fetching external content",
            0.0,
        )

        fetch_result = await self._fetch_content()
        if fetch_result.get("success"):
            items = fetch_result.get("items_fetched", 0)
            bytes_added = fetch_result.get("bytes_added", 0)
            yield self._make_event(
                pb.AMBIENT_PHASE_FETCH_CONTENT,
                f"Fetched {items} items ({bytes_added} bytes)",
                1.0,
                {
                    "items": str(items),
                    "bytes": str(bytes_added),
                    "latency_ms": str(fetch_result.get("latency_ms", 0)),
                },
            )
            self._total_daemon_tasks += 1
            self._successful_daemon_tasks += 1
            try:
                await self._buffer.compact_if_needed(self._summarize_compaction)
            except Exception as e:
                logger.error(
                    "Ambient compaction failed (thinking path).\n"
                    "  Guru: #BUF.00000001.COMPACTFAIL\n"
                    "  Try: /health fix endpoints\n"
                    "  %s",
                    e,
                )
                yield self._make_event(
                    pb.AMBIENT_PHASE_ERROR,
                    f"compaction failed: {e}",
                    1.0,
                )
        else:
            yield self._make_event(
                pb.AMBIENT_PHASE_FETCH_CONTENT,
                f"Fetch failed: {fetch_result.get('error', 'unknown')}",
                1.0,
            )
            self._total_daemon_tasks += 1

        # Independent axes: ingest now (no GPU). Compact after thinking is up.
        yield self._make_event(
            pb.AMBIENT_PHASE_FETCH_CONTENT,
            "Ticking Prospects ingest",
            0.0,
        )
        prospects_tick = await self._tick_prospects_ingest()
        yield self._make_event(
            pb.AMBIENT_PHASE_FETCH_CONTENT,
            (
                f"Prospects ingested={prospects_tick.get('ingested', 0)}"
                if not prospects_tick.get("error")
                else f"Prospects ingest failed: {prospects_tick['error']}"
            ),
            1.0,
            {k: str(v) for k, v in prospects_tick.items() if v is not None},
        )
        yield self._make_event(
            pb.AMBIENT_PHASE_FETCH_CONTENT,
            "Ticking Publishing ingest",
            0.0,
        )
        publishing_tick = await self._tick_publishing_ingest()
        yield self._make_event(
            pb.AMBIENT_PHASE_FETCH_CONTENT,
            (
                f"Publishing ingested={publishing_tick.get('ingested', 0)}"
                if not publishing_tick.get("error")
                else f"Publishing ingest failed: {publishing_tick['error']}"
            ),
            1.0,
            {k: str(v) for k, v in publishing_tick.items() if v is not None},
        )

        # Phase 1: Health check (after HN fetch so Complete cannot starve the FIFO)
        yield self._make_event(
            pb.AMBIENT_PHASE_BASELINE_HEALTH,
            "Checking endpoint health",
            0.0,
        )

        health_results = await self._verify_baseline_health()
        healthy_count = sum(1 for h in health_results.values() if h)

        yield self._make_event(
            pb.AMBIENT_PHASE_BASELINE_HEALTH,
            f"{healthy_count}/{len(self._baseline_endpoints)} healthy",
            1.0,
            {ep: "healthy" if h else "unhealthy" for ep, h in health_results.items()},
        )

        if not health_results.get("thinking"):
            logger.error(
                "Thinking vLLM is not HEALTHY; cognition synthesis cannot run.\n"
                "  Guru: #AMB.00000014.NOHEALTHY\n"
                "  Try: /health fix endpoints\n"
                "  Or:  /gpu status thinking"
            )
            self._total_daemon_tasks += 1
            yield self._make_event(
                pb.AMBIENT_PHASE_ERROR,
                "thinking vLLM not HEALTHY — synthesis blocked",
                1.0,
                {"thinking": "unhealthy"},
            )
        else:
            yield self._make_event(
                pb.AMBIENT_PHASE_BASELINE_WORKLOAD,
                "Compacting Prospects and Publishing independently",
                0.0,
            )
            compact_p = await self._tick_prospects_compact()
            compact_u = await self._tick_publishing_compact()
            yield self._make_event(
                pb.AMBIENT_PHASE_BASELINE_WORKLOAD,
                "Prospects/Publishing compact done",
                1.0,
                {
                    "prospects": str(compact_p),
                    "publishing": str(compact_u),
                },
            )
            yield self._make_event(
                pb.AMBIENT_PHASE_BASELINE_WORKLOAD,
                "Cognition synthesis (Publishing+Prospects+Ambient via Aperture)",
                0.0,
            )
            try:
                synth = await self._run_cognition_synthesis()
                self._total_daemon_tasks += 1
                self._successful_daemon_tasks += 1
                yield self._make_event(
                    pb.AMBIENT_PHASE_BASELINE_WORKLOAD,
                    f"synthesis episode={synth.get('episode_id', '')[:8]} "
                    f"agenda={synth.get('agenda', 0)}",
                    1.0,
                    {
                        "episode_id": str(synth.get("episode_id") or ""),
                        "hx_generation_id": str(synth.get("hx_generation_id") or ""),
                        "latency_ms": str(synth.get("latency_ms") or 0),
                    },
                )
            except Exception as e:
                logger.error(
                    "Cognition synthesis failed (thinking path).\n"
                    "  Guru: #COG.00000032.SYNTHFAIL\n"
                    "  Try: /health fix endpoints\n"
                    "  %s",
                    e,
                    exc_info=True,
                )
                self._total_daemon_tasks += 1
                yield self._make_event(
                    pb.AMBIENT_PHASE_ERROR,
                    f"synthesis failed: {e}",
                    1.0,
                )

        # Phase 2.55: Buffer Analysis (Bytez - subscription, zero marginal cost)
        yield self._make_event(
            pb.AMBIENT_PHASE_BUFFER_ANALYSIS,
            "Analyzing buffer with Bytez",
            0.0,
        )

        analysis_result = await self._analyze_buffer_with_bytez()
        if analysis_result.get("skipped"):
            yield self._make_event(
                pb.AMBIENT_PHASE_BUFFER_ANALYSIS,
                "Skipped: no new content",
                1.0,
            )
        elif analysis_result.get("success"):
            queries = analysis_result.get("queries_generated", 0)
            yield self._make_event(
                pb.AMBIENT_PHASE_BUFFER_ANALYSIS,
                f"Generated {queries} search queries",
                1.0,
                {
                    "queries": str(queries),
                    "latency_ms": str(analysis_result.get("latency_ms", 0)),
                },
            )
            self._total_daemon_tasks += 1
            self._successful_daemon_tasks += 1
        else:
            yield self._make_event(
                pb.AMBIENT_PHASE_BUFFER_ANALYSIS,
                f"Analysis failed: {analysis_result.get('error', 'unknown')}",
                1.0,
            )
            self._total_daemon_tasks += 1

        # Phase 2.6: Summarization (ALWAYS - core ambient work)
        yield self._make_event(
            pb.AMBIENT_PHASE_SUMMARIZATION,
            "Summarizing content",
            0.0,
        )

        summarize_result = await self._summarize_content()
        if summarize_result.get("success"):
            yield self._make_event(
                pb.AMBIENT_PHASE_SUMMARIZATION,
                f"Summary: {summarize_result.get('summary_length', 0)} chars",
                1.0,
                {"latency_ms": str(summarize_result.get("latency_ms", 0))},
            )
            self._total_daemon_tasks += 1
            self._successful_daemon_tasks += 1
        else:
            yield self._make_event(
                pb.AMBIENT_PHASE_SUMMARIZATION,
                f"Summarization failed: {summarize_result.get('error', 'unknown')}",
                1.0,
            )
            self._total_daemon_tasks += 1

        if baseline_only:
            duration_ms = int((time.time() - start_time) * 1000)
            yield self._make_event(
                pb.AMBIENT_PHASE_COMPLETE,
                f"Cycle complete ({duration_ms}ms)",
                1.0,
                {"duration_ms": str(duration_ms)},
            )
            return

        # Phase 3: Reasoning eviction
        yield self._make_event(
            pb.AMBIENT_PHASE_REASONING_EVICTION,
            "Preparing reasoning endpoint",
            0.0,
        )

        eviction_result = await self._evict_for_reasoning()
        if not eviction_result["success"]:
            yield self._make_event(
                pb.AMBIENT_PHASE_ERROR,
                f"Eviction failed: {eviction_result.get('error', 'unknown')}",
                0.0,
            )
            return

        allocated_endpoint = eviction_result.get("reasoning_endpoint")
        yield self._make_event(
            pb.AMBIENT_PHASE_REASONING_EVICTION,
            f"Ready, evicted: {eviction_result.get('evicted', [])}",
            1.0,
        )

        # Phase 4: Reasoning workload with varied prompt
        yield self._make_event(
            pb.AMBIENT_PHASE_REASONING_WORKLOAD,
            "Running reasoning task",
            0.0,
        )

        reasoning_prompt = random.choice(VARIED_REASONING_PROMPTS)
        reasoning_result = await self._run_reasoning_workload(
            custom_prompt=reasoning_prompt,
            endpoint_name=allocated_endpoint,
        )
        self._total_daemon_tasks += 1
        if reasoning_result.success:
            self._successful_daemon_tasks += 1

        yield self._make_event(
            pb.AMBIENT_PHASE_REASONING_WORKLOAD,
            f"{'Complete' if reasoning_result.success else 'Failed'} ({reasoning_result.latency_ms}ms)",
            1.0,
            {self._reasoning_endpoint: f"{reasoning_result.latency_ms}ms"} if reasoning_result.success else {},
        )

        # Phase 5: Restoration
        yield self._make_event(
            pb.AMBIENT_PHASE_BASELINE_RESTORATION,
            "Restoring baseline endpoints",
            0.0,
        )

        restoration_result = await self._restore_baseline()
        yield self._make_event(
            pb.AMBIENT_PHASE_BASELINE_RESTORATION,
            f"Restored: {restoration_result.get('restored', [])}",
            1.0,
        )

        duration_ms = int((time.time() - start_time) * 1000)
        yield self._make_event(
            pb.AMBIENT_PHASE_COMPLETE,
            f"Full cycle complete ({duration_ms}ms)",
            1.0,
            {"duration_ms": str(duration_ms)},
        )

    def _emit_event(
        self,
        phase: "pb.AmbientPhase",
        message: str,
        progress: float,
        metrics: Optional[dict[str, str]] = None,
    ) -> None:
        """Push event to queue for subscribers."""
        self._current_phase = AmbientPhase(
            {
                pb.AMBIENT_PHASE_BASELINE_HEALTH: "baseline_health",
                pb.AMBIENT_PHASE_BASELINE_WORKLOAD: "baseline_workload",
                pb.AMBIENT_PHASE_FETCH_CONTENT: "fetch_content",
                pb.AMBIENT_PHASE_BUFFER_ANALYSIS: "buffer_analysis",
                pb.AMBIENT_PHASE_SUMMARIZATION: "summarization",
                pb.AMBIENT_PHASE_REASONING_EVICTION: "reasoning_eviction",
                pb.AMBIENT_PHASE_REASONING_WORKLOAD: "reasoning_workload",
                pb.AMBIENT_PHASE_BASELINE_RESTORATION: "baseline_restoration",
                pb.AMBIENT_PHASE_COMPLETE: "complete",
                pb.AMBIENT_PHASE_ERROR: "error",
            }.get(phase, "complete")
        )

        event = self._make_event(phase, message, progress, metrics)

        # Add cycle info
        event.metrics["daemon_cycle"] = str(self._daemon_cycle)

        try:
            self._event_queue.put_nowait(event)
        except asyncio.QueueFull:
            # Drop oldest event if queue is full
            try:
                self._event_queue.get_nowait()
                self._event_queue.put_nowait(event)
            except asyncio.QueueEmpty:
                pass

    async def subscribe_events(self) -> AsyncIterator[pb.AmbientPhaseEvent]:
        """Stream events to a subscriber (TUI InfoPanel).

        Yields events as they are produced by the daemon loop.
        Completes when daemon stops and queue is drained.
        """
        while self._daemon_running or not self._event_queue.empty():
            try:
                event = await asyncio.wait_for(
                    self._event_queue.get(),
                    timeout=1.0,
                )
                yield event
            except asyncio.TimeoutError:
                # Check if we should continue waiting
                if not self._daemon_running and self._event_queue.empty():
                    break
                continue
            except asyncio.CancelledError:
                break

    # ─────────────────────────────────────────────────────────────────────────
    # Main Cycle Execution (Legacy - single shot)
    # ─────────────────────────────────────────────────────────────────────────

    async def run_cycle(
        self,
        skip_reasoning: bool = False,
        baseline_task_count: int = 1,
        reasoning_prompt: Optional[str] = None,
    ) -> AsyncIterator[pb.AmbientPhaseEvent]:
        """Execute a full ambient computing cycle with streaming progress.

        Args:
            skip_reasoning: If True, skip phases 3-4 (baseline only)
            baseline_task_count: Number of tasks per baseline endpoint
            reasoning_prompt: Custom reasoning prompt (or use default)

        Yields:
            AmbientPhaseEvent for each phase transition
        """
        if self._cycle_running:
            yield self._make_event(
                pb.AMBIENT_PHASE_ERROR,
                "Cycle already running",
                0.0,
            )
            return

        self._cycle_running = True
        start_time = time.time()
        phases_completed = 0
        total_tasks = 0
        successful_tasks = 0
        endpoint_latencies: dict[str, list[int]] = {}

        try:
            # Phase 1: Baseline health check
            self._current_phase = AmbientPhase.BASELINE_HEALTH
            yield self._make_event(
                pb.AMBIENT_PHASE_BASELINE_HEALTH,
                "Checking baseline endpoint health",
                0.0,
            )

            health_results = await self._verify_baseline_health()
            healthy_count = sum(1 for h in health_results.values() if h)

            if healthy_count == 0:
                yield self._make_event(
                    pb.AMBIENT_PHASE_ERROR,
                    f"No healthy baseline endpoints (0/{len(self._baseline_endpoints)})",
                    0.0,
                    {"healthy": str(healthy_count), "total": str(len(self._baseline_endpoints))},
                )
                self._finalize_cycle(False, phases_completed, total_tasks, successful_tasks, {}, start_time, "No healthy endpoints")
                return

            phases_completed = 1
            yield self._make_event(
                pb.AMBIENT_PHASE_BASELINE_HEALTH,
                f"Baseline health verified ({healthy_count}/{len(self._baseline_endpoints)} healthy)",
                1.0,
                {ep: "healthy" if h else "unhealthy" for ep, h in health_results.items()},
            )

            if not health_results.get("thinking"):
                yield self._make_event(
                    pb.AMBIENT_PHASE_ERROR,
                    "thinking vLLM not HEALTHY — synthesis blocked",
                    0.0,
                    {"thinking": "unhealthy"},
                )
                self._finalize_cycle(
                    False,
                    phases_completed,
                    total_tasks,
                    successful_tasks,
                    {},
                    start_time,
                    "thinking vLLM not HEALTHY. Try: /health fix endpoints",
                )
                return

            # Phase 2: Cognition synthesis is the health workload (not toy Completes)
            self._current_phase = AmbientPhase.BASELINE_WORKLOAD
            yield self._make_event(
                pb.AMBIENT_PHASE_BASELINE_WORKLOAD,
                "Cognition synthesis (Publishing+Prospects+Ambient)",
                0.0,
            )
            synth = await self._run_cognition_synthesis()
            total_tasks += 1
            successful_tasks += 1
            endpoint_latencies.setdefault("thinking", []).append(
                int(synth.get("latency_ms") or 0)
            )
            phases_completed = 2
            yield self._make_event(
                pb.AMBIENT_PHASE_BASELINE_WORKLOAD,
                f"synthesis episode={str(synth.get('episode_id') or '')[:8]}",
                1.0,
                {
                    "episode_id": str(synth.get("episode_id") or ""),
                    "hx_generation_id": str(synth.get("hx_generation_id") or ""),
                },
            )

            # Skip reasoning phases if requested
            if skip_reasoning:
                phases_completed = 5  # Mark as complete
                yield self._make_event(
                    pb.AMBIENT_PHASE_COMPLETE,
                    "Baseline-only cycle complete",
                    1.0,
                    self._compute_avg_latencies(endpoint_latencies),
                )
                self._finalize_cycle(
                    True, phases_completed, total_tasks, successful_tasks,
                    self._compute_avg_latencies(endpoint_latencies), start_time, ""
                )
                return

            # Phase 3: Reasoning eviction
            self._current_phase = AmbientPhase.REASONING_EVICTION
            yield self._make_event(
                pb.AMBIENT_PHASE_REASONING_EVICTION,
                "Preparing for reasoning workload",
                0.0,
            )

            eviction_result = await self._evict_for_reasoning()
            if not eviction_result["success"]:
                yield self._make_event(
                    pb.AMBIENT_PHASE_ERROR,
                    f"Failed to prepare for reasoning: {eviction_result.get('error', 'unknown')}",
                    0.0,
                )
                self._finalize_cycle(
                    False, phases_completed, total_tasks, successful_tasks,
                    self._compute_avg_latencies(endpoint_latencies), start_time,
                    eviction_result.get("error", "Eviction failed")
                )
                return

            phases_completed = 3
            # Get the allocated reasoning endpoint from the eviction result
            allocated_reasoning_endpoint = eviction_result.get("reasoning_endpoint")
            yield self._make_event(
                pb.AMBIENT_PHASE_REASONING_EVICTION,
                f"Reasoning endpoint ready, evicted: {eviction_result.get('evicted', [])}",
                1.0,
            )

            # Phase 4: Reasoning workload
            self._current_phase = AmbientPhase.REASONING_WORKLOAD
            yield self._make_event(
                pb.AMBIENT_PHASE_REASONING_WORKLOAD,
                "Running reasoning task",
                0.0,
            )

            reasoning_result = await self._run_reasoning_workload(
                custom_prompt=reasoning_prompt,
                endpoint_name=allocated_reasoning_endpoint,
            )
            total_tasks += 1

            if reasoning_result.success:
                successful_tasks += 1
                endpoint_latencies[self._reasoning_endpoint] = [reasoning_result.latency_ms]

            phases_completed = 4
            yield self._make_event(
                pb.AMBIENT_PHASE_REASONING_WORKLOAD,
                f"Reasoning task {'complete' if reasoning_result.success else 'failed'} ({reasoning_result.latency_ms}ms)",
                1.0,
                {self._reasoning_endpoint: f"{reasoning_result.latency_ms}ms"} if reasoning_result.success else {},
            )

            # Phase 5: Baseline restoration
            self._current_phase = AmbientPhase.BASELINE_RESTORATION
            yield self._make_event(
                pb.AMBIENT_PHASE_BASELINE_RESTORATION,
                "Restoring baseline endpoints",
                0.0,
            )

            restoration_result = await self._restore_baseline()

            phases_completed = 5
            yield self._make_event(
                pb.AMBIENT_PHASE_BASELINE_RESTORATION,
                f"Baseline restored: {restoration_result.get('restored', [])}",
                1.0,
            )

            # Complete
            self._current_phase = AmbientPhase.COMPLETE
            avg_latencies = self._compute_avg_latencies(endpoint_latencies)
            yield self._make_event(
                pb.AMBIENT_PHASE_COMPLETE,
                f"Full cycle complete ({successful_tasks}/{total_tasks} tasks)",
                1.0,
                avg_latencies,
            )

            self._finalize_cycle(
                True, phases_completed, total_tasks, successful_tasks,
                avg_latencies, start_time, ""
            )

        except Exception as e:
            logger.exception("Ambient cycle error")
            self._current_phase = AmbientPhase.ERROR
            yield self._make_event(
                pb.AMBIENT_PHASE_ERROR,
                str(e),
                0.0,
            )
            self._finalize_cycle(
                False, phases_completed, total_tasks, successful_tasks,
                self._compute_avg_latencies(endpoint_latencies), start_time, str(e)
            )
        finally:
            self._cycle_running = False

    # ─────────────────────────────────────────────────────────────────────────
    # Phase Implementations
    # ─────────────────────────────────────────────────────────────────────────

    async def _verify_baseline_health(self) -> dict[str, bool]:
        """Verify all baseline endpoints are healthy.

        Returns:
            Dict mapping endpoint name to health status
        """
        results = {}

        thinking = self._orchestrator.get_endpoint_status("thinking")
        thinking_loading = thinking is not None and (thinking.status or "").lower() in {
            "starting",
            "process_status_starting",
        }
        for endpoint in self._baseline_endpoints:
            if thinking_loading and endpoint != "thinking":
                logger.info(
                    "Ambient skip ensure %s: thinking still %s",
                    endpoint,
                    thinking.status,
                )
                results[endpoint] = False
                continue
            try:
                status = await self._orchestrator.ensure_endpoint(endpoint)
                results[endpoint] = status.status == ProcessStatus.HEALTHY.value
            except Exception as e:
                logger.warning(f"Health check failed for {endpoint}: {e}")
                results[endpoint] = False

        return results

    async def _summarize_compaction(self, prompt: str) -> str:
        from gaius.engine.services.cognition_buffer import thinking_output_tokens

        response = await self._backend_router.complete(
            prompt=prompt,
            agent_alias="thinking",
            max_tokens=thinking_output_tokens(prompt),
            temperature=0.2,
            task_type="buffer_compaction",
            enable_thinking=True,
            preserve_thinking=True,
        )
        if getattr(response, "error", None):
            raise RuntimeError(str(response.error))
        text = (getattr(response, "content", None) or "").strip()
        if not text:
            text = (getattr(response, "reasoning_content", None) or "").strip()
        if not text:
            raise RuntimeError("empty thinking compaction")
        return text

    async def _tick_prospects_ingest(self) -> dict[str, Any]:
        ps = self._prospects_service
        if ps is None:
            logger.error(
                "Prospects axis not attached to Ambient.\n"
                "  Guru: #PS.00000008.NOATTACH"
            )
            return {"error": "prospects not attached"}
        try:
            return await ps.ingest_market_buffer()
        except Exception as e:
            logger.error(
                "Prospects ingest failed.\n  Guru: #PS.00000003.FMPFAIL\n  %s", e
            )
            return {"error": str(e)}

    async def _tick_prospects_compact(self) -> dict[str, Any]:
        ps = self._prospects_service
        if ps is None:
            return {"error": "prospects not attached"}
        try:
            return await ps.compact_buffer()
        except Exception as e:
            logger.error(
                "Prospects compact failed.\n  Guru: #BUF.00000001.COMPACTFAIL\n  %s",
                e,
            )
            return {"error": str(e)}

    async def _tick_publishing_ingest(self) -> dict[str, Any]:
        axis = self._publishing_axis
        if axis is None:
            logger.error(
                "Publishing axis not attached to Ambient.\n"
                "  Guru: #COG.00000032.SYNTHFAIL"
            )
            return {"error": "publishing not attached"}
        try:
            return await axis.ingest()
        except Exception as e:
            logger.error("Publishing ingest failed.\n  %s", e)
            return {"error": str(e)}

    async def _tick_publishing_compact(self) -> dict[str, Any]:
        axis = self._publishing_axis
        buf = self._publishing_buffer
        if axis is None or buf is None:
            return {"error": "publishing not attached"}
        summarize = getattr(axis, "_summarize", None) or self._summarize_compaction
        try:
            return await buf.compact_if_needed(summarize)
        except Exception as e:
            logger.error(
                "Publishing compact failed.\n  Guru: #BUF.00000001.COMPACTFAIL\n  %s",
                e,
            )
            return {"error": str(e)}

    async def _run_cognition_synthesis(self) -> dict[str, Any]:
        """Publishing + Prospects + Ambient → thinking → buffer + agenda."""
        from gaius.engine.services.cognition_synthesis import run_synthesis_cycle

        return await run_synthesis_cycle(
            backend_router=self._backend_router,
            db_pool=self._db_pool,
            ambient_buffer=self._buffer,
            prospects_service=self._prospects_service,
            publishing_buffer=self._publishing_buffer,
        )

    async def _fetch_content(self) -> dict[str, Any]:
        """Fetch external content and add to buffer.

        Uses HNFetcher to fetch from Hacker News and adds content
        to the ambient buffer for later summarization.

        Returns:
            Dict with success, item_count, bytes_added, and buffer stats
        """
        import httpx
        from gaius.workers.fetchers.hackernews import HNFetcher
        from gaius.workers.models import FeedSource, SourceType
        from gaius.workers.config import WorkerConfig

        buffer_cfg = self._config.ambient_buffer
        start_time = time.time()

        try:
            # Create a virtual source for HN fetch
            source = FeedSource(
                id=0,  # Virtual source
                name="ambient-hn",
                source_type=SourceType.HACKERNEWS,
                base_url=buffer_cfg.source_url,
                config={
                    "firebase_stories": True,
                    "newcomments": False,
                    "max_items": max(buffer_cfg.max_items, 15),
                    "buffer_only": True,  # Always buffer-only for ambient
                },
            )

            # Create fetcher with required dependencies
            # Overall timeout of 60s for the entire fetch phase
            worker_config = WorkerConfig()
            async with httpx.AsyncClient(timeout=30.0) as http_client:
                fetcher = HNFetcher(worker_config, http_client)

                # Wrap fetch in timeout to prevent runaway cycles
                result = await asyncio.wait_for(
                    fetcher.fetch(source),
                    timeout=60,  # 60s max for entire fetch phase
                )

                if result.error:
                    return {
                        "success": False,
                        "error": result.error,
                        "latency_ms": int((time.time() - start_time) * 1000),
                    }

                # Add fetched items to buffer
                bytes_added = 0
                for item in result.items:
                    content = item.content or item.summary or item.title
                    if content:
                        # Build metadata with author and story info
                        item_meta = item.metadata or {}
                        meta = {
                            "title": item.title,
                            "hn_id": item_meta.get("hn_id"),
                            "is_comment": item_meta.get("is_comment", False),
                            "fetched_at": datetime.now().isoformat(),
                        }
                        # Include author if available
                        if item_meta.get("author"):
                            meta["author"] = item_meta["author"]
                        elif item.authors:
                            meta["author"] = item.authors[0]
                        # Include story info if available
                        if item_meta.get("story_title"):
                            meta["story_title"] = item_meta["story_title"]
                        if item_meta.get("story_id"):
                            meta["story_id"] = item_meta["story_id"]

                        entry = BufferEntry.create(
                            role=BufferRole.CONTENT,
                            content=content,
                            source_url=item.url or "",
                            metadata=meta,
                        )
                        await self._buffer.add_entry(entry)
                        bytes_added += entry.content_bytes

                latency_ms = int((time.time() - start_time) * 1000)

                return {
                    "success": True,
                    "items_fetched": len(result.items),
                    "bytes_added": bytes_added,
                    "buffer_stats": self._buffer.get_stats(),
                    "latency_ms": latency_ms,
                }

        except asyncio.TimeoutError:
            return {
                "success": False,
                "error": "Fetch timeout (60s)",
                "latency_ms": int((time.time() - start_time) * 1000),
            }
        except Exception as e:
            logger.exception("Fetch content failed")
            return {
                "success": False,
                "error": str(e),
                "latency_ms": int((time.time() - start_time) * 1000),
            }

    async def _summarize_content(self) -> dict[str, Any]:
        """Summarize buffered content using reasoning endpoint.

        Takes content from buffer and creates a summary using the
        reasoning (or fast) endpoint. Adds summary back to buffer
        with role=SUMMARY.

        Returns:
            Dict with success, summary_length, and latency
        """
        buffer_cfg = self._config.ambient_buffer
        start_time = time.time()

        try:
            # Get recent content entries from buffer
            content_entries = await self._buffer.get_entries_by_role(
                BufferRole.CONTENT, limit=10
            )

            if not content_entries:
                return {
                    "success": True,
                    "message": "No content to summarize",
                    "latency_ms": int((time.time() - start_time) * 1000),
                }

            # Build prompt from content entries
            content_texts = []
            for entry in content_entries:
                title = entry.metadata.get("title", "")
                preview = entry.content_preview
                if title:
                    content_texts.append(f"- {title}: {preview}")
                else:
                    content_texts.append(f"- {preview}")

            content_block = "\n".join(content_texts)
            summarize_prompt = (
                "Summarize the key themes from these Hacker News items in 2-3 sentences:\n\n"
                f"{content_block}\n\n"
                "Focus on the most interesting or important topics."
            )

            if self._gpu_paused:
                return {
                    "success": True,
                    "message": "GPU paused (YK preempt); buffer kept",
                    "latency_ms": int((time.time() - start_time) * 1000),
                    "skipped": True,
                }

            # Same thinking process (Qwen3.8) — 1:1 with gaius-thinking.
            # Do not mint a second Application or occupy Docling extract.
            from gaius.engine.sentinel_claim import (
                capability_workload_id,
                gpu_start_allowed,
            )

            think_id = capability_workload_id("thinking")
            if not gpu_start_allowed(think_id):
                return {
                    "success": True,
                    "message": "thinking process has no sentinel; skip summarize",
                    "skipped": True,
                    "latency_ms": int((time.time() - start_time) * 1000),
                }

            from gaius.engine.services.cognition_buffer import (
                thinking_output_tokens,
                thinking_read_timeout_s,
            )

            max_tok = thinking_output_tokens(summarize_prompt)
            response = await asyncio.wait_for(
                self._backend_router.complete(
                    prompt=summarize_prompt,
                    agent_alias="thinking",
                    max_tokens=max_tok,
                    temperature=1.0,
                    task_type="ambient_summarization",
                    enable_thinking=True,
                    preserve_thinking=True,
                ),
                timeout=thinking_read_timeout_s(max_tok),
            )

            latency_ms = int((time.time() - start_time) * 1000)

            if response.error:
                return {
                    "success": False,
                    "error": response.error,
                    "latency_ms": latency_ms,
                }

            if getattr(response, "reasoning_content", ""):
                think_entry = BufferEntry.create(
                    role=BufferRole.ASSISTANT,
                    content=response.reasoning_content,
                    metadata={
                        "kind": "thinking",
                        "source_count": len(content_entries),
                    },
                )
                await self._buffer.add_entry(think_entry)

            # Add summary to buffer
            summary_entry = BufferEntry.create(
                role=BufferRole.SUMMARY,
                content=response.content or "",
                metadata={
                    "source_count": len(content_entries),
                    "created_at": datetime.now().isoformat(),
                },
            )
            await self._buffer.add_entry(summary_entry)

            return {
                "success": True,
                "summary_length": len(response.content or ""),
                "source_count": len(content_entries),
                "latency_ms": latency_ms,
            }

        except asyncio.TimeoutError:
            return {
                "success": False,
                "error": "Summarization timeout",
                "latency_ms": int((time.time() - start_time) * 1000),
            }
        except Exception as e:
            logger.exception("Summarization failed")
            return {
                "success": False,
                "error": str(e),
                "latency_ms": int((time.time() - start_time) * 1000),
            }

    async def _run_brave_proposals(self, queries: list[str]) -> dict[str, Any]:
        """Execute Brave Search on Bytez proposals; store hits as CONTENT."""
        import httpx

        from gaius.core.config import get_config as _get_config

        api_key = os.environ.get("BRAVE_API_KEY") or _get_config().providers.brave.api_key
        if not api_key:
            logger.error(
                "BRAVE_API_KEY missing; SEARCH_QUERY entries not retrieved.\n"
                "  Guru: #AMB.00000015.NOBRAVE"
            )
            return {"hits": 0, "error": "no brave key"}
        hits = 0
        async with httpx.AsyncClient(timeout=20.0) as client:
            for query in queries[:3]:
                try:
                    resp = await client.get(
                        "https://api.search.brave.com/res/v1/web/search",
                        params={"q": query, "count": "5"},
                        headers={
                            "Accept": "application/json",
                            "X-Subscription-Token": api_key,
                        },
                    )
                    if resp.status_code != 200:
                        logger.error(
                            "Brave search HTTP %s for %r.\n  Guru: #AMB.00000016.BRAVEHTTP",
                            resp.status_code,
                            query[:80],
                        )
                        continue
                    web = (resp.json() or {}).get("web") or {}
                    results = web.get("results") or []
                    for row in results[:5]:
                        title = str(row.get("title") or "")
                        url = str(row.get("url") or "")
                        desc = str(row.get("description") or "")
                        if not title or not url:
                            continue
                        entry = BufferEntry.create(
                            role=BufferRole.CONTENT,
                            content=f"{title}\n{url}\n{desc}",
                            source_url=url,
                            metadata={
                                "source": "brave",
                                "query": query,
                                "title": title,
                            },
                        )
                        await self._buffer.add_entry(entry)
                        hits += 1
                except Exception as e:
                    logger.error(
                        "Brave search failed for %r: %s\n  Guru: #AMB.00000016.BRAVEHTTP",
                        query[:80],
                        e,
                    )
        return {"hits": hits}

    async def _analyze_buffer_with_bytez(self) -> dict[str, Any]:
        """Analyze new HN comments via Bytez, generate Brave Search queries.

        Uses Bytez (subscription-based, zero marginal cost) to analyze
        newly fetched HN comments and generate 3 candidate Brave Search
        queries for downstream research.

        Skips if no new (unanalyzed) content exists in the buffer.

        Returns:
            Dict with success, queries_generated, skipped (if no new content)
        """
        from ..backends.external.bytez_backend import BytezBackend

        start_time = time.time()

        try:
            # Get unanalyzed content entries
            content_entries = await self._buffer.get_entries_by_role(
                BufferRole.CONTENT
            )
            new_entries = [
                e for e in content_entries
                if not e.metadata.get("analyzed_at")
            ]

            if not new_entries:
                return {
                    "success": True,
                    "skipped": True,
                    "reason": "No new content to analyze",
                    "latency_ms": int((time.time() - start_time) * 1000),
                }

            # Build analysis prompt from recent unanalyzed entries
            content_block = "\n".join(
                [
                    f"- {e.metadata.get('title') or e.metadata.get('story_title') or 'HN'}"
                    f" {e.source_url}: {e.content_preview}"
                    for e in new_entries[:10]
                ]
            )

            prompt = f"""Analyze these Hacker News stories and generate exactly 3 Brave Search queries
that would help research the topics. Prefer queries that match story URLs and titles
(products, papers, companies, technical claims).

Stories:
{content_block}

Output exactly 3 search queries, one per line, no numbering or bullets:"""

            # Initialize Bytez backend
            bytez = BytezBackend()
            if not bytez.is_available:
                return {
                    "success": False,
                    "error": "Bytez API not configured (BYTEZ_API_KEY)",
                    "latency_ms": int((time.time() - start_time) * 1000),
                }

            # Call Bytez with timeout (60s for larger models like Mistral-7B)
            response = await asyncio.wait_for(
                bytez.complete(
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=256,
                    temperature=0.7,
                ),
                timeout=60,
            )

            if not response.success:
                return {
                    "success": False,
                    "error": response.error or "Bytez completion failed",
                    "latency_ms": int((time.time() - start_time) * 1000),
                }

            # Parse queries (one per line, max 3)
            queries = [
                q.strip()
                for q in response.content.strip().split("\n")
                if q.strip()
            ][:3]

            # Add queries to buffer with SEARCH_QUERY role
            for query in queries:
                entry = BufferEntry.create(
                    role=BufferRole.SEARCH_QUERY,
                    content=query,
                    metadata={
                        "source": "bytez_analysis",
                        "generated_at": datetime.now().isoformat(),
                        "hn_ids": [
                            e.metadata.get("hn_id")
                            for e in new_entries[:10]
                        ],
                    },
                )
                await self._buffer.add_entry(entry)

            # Mark analyzed entries so they're not reprocessed
            now = datetime.now().isoformat()
            for entry in new_entries:
                entry.metadata["analyzed_at"] = now

            brave = await self._run_brave_proposals(queries)
            latency_ms = int((time.time() - start_time) * 1000)
            logger.info(
                f"Bytez analysis generated {len(queries)} search queries "
                f"from {len(new_entries)} entries; brave_hits={brave.get('hits', 0)} "
                f"({latency_ms}ms)"
            )

            return {
                "success": True,
                "queries_generated": len(queries),
                "queries": queries,
                "brave_hits": brave.get("hits", 0),
                "entries_analyzed": len(new_entries),
                "latency_ms": latency_ms,
            }

        except asyncio.TimeoutError:
            record_exception_caught(
                component="ambient",
                operation="bytez_analysis",
                exception_type="TimeoutError",
            )
            return {
                "success": False,
                "error": "Bytez analysis timeout (60s)",
                "latency_ms": int((time.time() - start_time) * 1000),
            }
        except Exception as e:
            logger.exception("Bytez buffer analysis failed")
            record_exception_caught(
                component="ambient",
                operation="bytez_analysis",
                exception_type=type(e).__name__,
            )
            return {
                "success": False,
                "error": str(e),
                "latency_ms": int((time.time() - start_time) * 1000),
            }

    async def _execute_task(self, task: AmbientTask) -> TaskResult:
        """Execute a single ambient task.

        Args:
            task: Task to execute

        Returns:
            TaskResult with latency and success status

        Note:
            Metrics are recorded automatically by BackendRouter.route()
            at the core inference layer.
        """
        start_time = time.time()

        try:
            response = await asyncio.wait_for(
                self._backend_router.complete(
                    prompt=task.prompt,
                    agent_alias=task.endpoint,
                    system_prompt=task.system_prompt or None,
                    max_tokens=256,  # Short responses for testing
                    temperature=0.7,
                    task_type="ambient_warmup",
                ),
                timeout=task.timeout_secs,
            )

            latency_ms = int((time.time() - start_time) * 1000)

            # Check for error in response
            if response.error:
                return TaskResult(
                    endpoint=task.endpoint,
                    success=False,
                    latency_ms=latency_ms,
                    error=response.error,
                )

            return TaskResult(
                endpoint=task.endpoint,
                success=True,
                latency_ms=latency_ms,
                response_length=len(response.content) if response.content else 0,
            )

        except asyncio.TimeoutError:
            latency_ms = int((time.time() - start_time) * 1000)
            return TaskResult(
                endpoint=task.endpoint,
                success=False,
                latency_ms=latency_ms,
                error=f"Timeout after {task.timeout_secs}s",
            )
        except Exception as e:
            latency_ms = int((time.time() - start_time) * 1000)
            return TaskResult(
                endpoint=task.endpoint,
                success=False,
                latency_ms=latency_ms,
                error=str(e),
            )

    async def _evict_for_reasoning(self) -> dict[str, Any]:
        """Keep Qwen3.8 thinking. Do not evict TP=4 for cap_reasoning (QwQ).

        Thinking is the live reasoning endpoint. A HIGH-priority REASONING
        workload used to start QwQ-32B and stop thinking.

        Returns:
            Dict with success status and the thinking endpoint name
        """
        try:
            if self._orchestrator is None:
                return {"success": False, "error": "orchestrator not bound"}

            status = self._orchestrator.get_endpoint_status("thinking")
            if status is None or status.status not in ("healthy", "starting"):
                status = await self._orchestrator.ensure_endpoint("thinking")

            return {
                "success": status is not None and status.status in (
                    "healthy",
                    "starting",
                    "optillm",
                ),
                "evicted": [],
                "restore_plan": [],
                "reasoning_endpoint": "thinking",
                "reasoning_port": status.port if status else None,
                "workload_id": None,
            }

        except Exception as e:
            logger.exception("Eviction failed")
            return {
                "success": False,
                "error": str(e),
            }

    async def _run_reasoning_workload(
        self,
        custom_prompt: Optional[str] = None,
        endpoint_name: Optional[str] = None,
    ) -> TaskResult:
        """Run the reasoning workload task.

        Args:
            custom_prompt: Optional custom prompt
            endpoint_name: Optional endpoint name (from scheduler allocation)

        Returns:
            TaskResult for reasoning
        """
        # Use the scheduler-allocated endpoint if provided, otherwise fallback
        target_endpoint = endpoint_name or self._reasoning_endpoint

        task = AmbientTask(
            endpoint=target_endpoint,
            prompt=custom_prompt or DEFAULT_REASONING_TASK.prompt,
            expected_capability="reasoning",
            timeout_secs=120,
        )

        return await self._execute_task(task)

    async def _restore_baseline(self) -> dict[str, Any]:
        """Restore baseline endpoints after reasoning completes.

        Tracks restoration transitions via AgendaTracker for incident tracking.

        Returns:
            Dict with restoration status
        """
        try:
            # Record restoration transitions BEFORE completing workload
            # This ensures the transitions are recorded with POSITIVE control
            # Note: ABSENT represents a stopped/non-running endpoint state
            if self._agenda_tracker and self._evicted_endpoints:
                from ..resources.reconciliation import EndpointState
                from ..incidents import ControlMode

                for endpoint in self._evicted_endpoints:
                    try:
                        await self._agenda_tracker.on_endpoint_transition(
                            endpoint=endpoint,
                            from_state=EndpointState.ABSENT,  # Was stopped (ABSENT)
                            to_state=EndpointState.HEALTHY,
                            observed_control=ControlMode.POSITIVE,  # Orchestrated restoration
                        )
                        logger.debug(f"Recorded restoration transition for {endpoint}")
                    except Exception as e:
                        logger.warning(f"Failed to record restoration transition for {endpoint}: {e}")

            # Complete the workload to trigger restoration
            # The orchestrator tracks active workloads and will restore
            workloads = self._orchestrator.get_active_workloads()

            restored = []
            # workloads is dict[str, dict] - iterate over items
            for workload_id, workload_info in workloads.items():
                if workload_id.startswith("ambient-reasoning-"):
                    await self._orchestrator.complete_workload(workload_id)
                    # restore_plan is a list in the workload info dict
                    restored.extend(workload_info.get("restore_plan", []))

            # Ensure baseline endpoints are running
            for endpoint in self._baseline_endpoints:
                try:
                    await self._orchestrator.ensure_endpoint(endpoint)
                    if endpoint not in restored:
                        restored.append(endpoint)
                except Exception as e:
                    logger.warning(f"Failed to restore {endpoint}: {e}")

            # Clear tracking state after successful restoration
            self._current_workload_id = None
            self._evicted_endpoints = []

            return {
                "success": True,
                "restored": restored,
            }

        except Exception as e:
            logger.exception("Restoration failed")
            return {
                "success": False,
                "error": str(e),
            }

    # ─────────────────────────────────────────────────────────────────────────
    # Helpers
    # ─────────────────────────────────────────────────────────────────────────

    def _make_event(
        self,
        phase: "pb.AmbientPhase",
        message: str,
        progress: float,
        metrics: Optional[dict[str, str]] = None,
    ) -> pb.AmbientPhaseEvent:
        """Create a protobuf AmbientPhaseEvent."""
        event = pb.AmbientPhaseEvent(
            phase=phase,
            message=message,
            progress=progress,
            timestamp_ms=int(time.time() * 1000),
        )
        if metrics:
            for k, v in metrics.items():
                event.metrics[k] = v
        return event

    def _compute_avg_latencies(
        self,
        latencies: dict[str, list[int]],
    ) -> dict[str, str]:
        """Compute average latencies per endpoint."""
        return {
            ep: f"{sum(lats) // len(lats)}ms"
            for ep, lats in latencies.items()
            if lats
        }

    def _finalize_cycle(
        self,
        success: bool,
        phases_completed: int,
        total_tasks: int,
        successful_tasks: int,
        endpoint_latencies: dict[str, str],
        start_time: float,
        error_message: str,
    ) -> None:
        """Finalize cycle and record result."""
        duration_ms = int((time.time() - start_time) * 1000)

        # Convert string latencies to int
        int_latencies = {}
        for ep, lat in endpoint_latencies.items():
            try:
                int_latencies[ep] = int(lat.replace("ms", ""))
            except (ValueError, AttributeError):
                pass

        self._last_result = CycleResult(
            success=success,
            phases_completed=phases_completed,
            total_tasks=total_tasks,
            successful_tasks=successful_tasks,
            endpoint_latencies=int_latencies,
            error_message=error_message,
            duration_ms=duration_ms,
        )

        self._last_cycle_at = datetime.now()
        if success:
            self._cycles_completed += 1

        logger.info(
            f"Ambient cycle {'complete' if success else 'failed'}: "
            f"phases={phases_completed}, tasks={successful_tasks}/{total_tasks}, "
            f"duration={duration_ms}ms"
        )

    # ─────────────────────────────────────────────────────────────────────────
    # State Persistence (for auto-restart after engine restart)
    # ─────────────────────────────────────────────────────────────────────────

    async def _persist_daemon_state(self, running: bool) -> None:
        """Persist daemon state to database for auto-restart.

        Uses the update_ambient_daemon_state() database function to
        atomically update the singleton state row.

        Args:
            running: Whether the daemon should be marked as running
        """
        if not self._db_pool:
            logger.debug("No db_pool, skipping state persistence")
            return

        try:
            async with self._db_pool.acquire() as conn:
                await conn.execute(
                    """
                    SELECT update_ambient_daemon_state(
                        $1,  -- running
                        $2,  -- baseline_only (not persisted in current impl, default false)
                        $3,  -- max_cycles
                        $4,  -- cycles_completed
                        $5,  -- total_tasks
                        $6   -- successful_tasks
                    )
                    """,
                    running,
                    False,  # baseline_only - could persist this too
                    self._max_cycles,
                    self._daemon_cycle,
                    self._total_daemon_tasks,
                    self._successful_daemon_tasks,
                )
            logger.debug(
                f"Persisted ambient daemon state: running={running}, "
                f"cycles={self._daemon_cycle}, tasks={self._total_daemon_tasks}"
            )
        except Exception as e:
            logger.warning(f"Failed to persist daemon state: {e}")

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
        except Exception as e:
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
        except Exception as e:
            logger.warning("set preempted failed: %s", e)

    async def pause_gpu(self, reason: str = "yield") -> None:
        """YK preempt: stop calling thinking. RAM buffer stays."""
        self._gpu_paused = True
        await self._set_preempted(True)
        logger.info("Ambient GPU paused (%s); buffer retained", reason)

    async def resume_gpu(self) -> None:
        self._gpu_paused = False
        await self._set_preempted(False)
        logger.info("Ambient GPU resumed")

    async def ensure_started_on_boot(self) -> dict[str, Any]:
        """Start or resume Ambient unless the operator stopped it."""
        auto_start = self._config.startup.auto_start_ambient
        state = await self.load_persisted_state()
        action = ambient_boot_action(state, auto_start=auto_start)
        if action == "skip":
            return {
                "status": "skipped",
                "message": "auto-start off or operator-disabled",
            }
        if action == "resume":
            return await self.resume_from_persisted_state()
        started = await self.start_daemon()
        return {"status": "started" if started.get("success") else "error", **started}

    async def _increment_cycle_in_db(self, tasks_in_cycle: int, successful: int) -> None:
        """Increment cycle count in database after each cycle.

        Args:
            tasks_in_cycle: Number of tasks executed in this cycle
            successful: Number of successful tasks
        """
        if not self._db_pool:
            return

        try:
            async with self._db_pool.acquire() as conn:
                await conn.execute(
                    "SELECT increment_ambient_cycle($1, $2)",
                    tasks_in_cycle,
                    successful,
                )
        except Exception as e:
            logger.warning(f"Failed to increment cycle in DB: {e}")

    async def load_persisted_state(self) -> Optional[dict[str, Any]]:
        """Load persisted daemon state from database.

        Returns:
            Dict with running, baseline_only, max_cycles, cycles_completed,
            total_tasks, successful_tasks, started_at, or None if no state.
        """
        if not self._db_pool:
            logger.debug("No db_pool, cannot load persisted state")
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
                if row:
                    return dict(row)
                return None
        except Exception as e:
            logger.warning(f"Failed to load persisted state: {e}")
            return None

    async def resume_from_persisted_state(self) -> dict[str, Any]:
        """Resume daemon from persisted state if it was running.

        Called during engine startup to auto-resume ambient workload.

        Returns:
            Dict with status: 'resumed', 'not_running', or 'error'
        """
        state = await self.load_persisted_state()

        if not state:
            return {"status": "not_running", "message": "No persisted state found"}

        if not state.get("running"):
            return {
                "status": "not_running",
                "message": "Daemon was not running before shutdown",
                "last_stopped": state.get("stopped_at"),
            }

        # Restore state from DB
        baseline_only = state.get("baseline_only", False)
        max_cycles = state.get("max_cycles")
        cycles_completed = state.get("cycles_completed", 0)
        total_tasks = state.get("total_tasks", 0)
        successful_tasks = state.get("successful_tasks", 0)
        started_at = state.get("started_at")

        logger.info(
            f"Resuming ambient daemon from persisted state: "
            f"cycles={cycles_completed}, tasks={total_tasks}, "
            f"started_at={started_at}"
        )

        # Restore counters before starting
        self._daemon_cycle = cycles_completed
        self._total_daemon_tasks = total_tasks
        self._successful_daemon_tasks = successful_tasks
        if started_at:
            self._daemon_started_at = started_at

        # Start the daemon (will continue from where it left off)
        result = await self.start_daemon(
            baseline_only=baseline_only,
            max_cycles=max_cycles,
        )

        if result.get("success"):
            return {
                "status": "resumed",
                "message": f"Resumed from cycle {cycles_completed}",
                "cycles_completed": cycles_completed,
                "total_tasks": total_tasks,
                "baseline_only": baseline_only,
            }
        else:
            return {
                "status": "error",
                "message": result.get("message", "Failed to resume"),
            }

    # ─────────────────────────────────────────────────────────────────────────
    # Buffer Export
    # ─────────────────────────────────────────────────────────────────────────

    async def export_buffer(self, kb_root: str = "build/dev") -> dict[str, Any]:
        """Export buffer contents to zettelkasten file.

        Creates file at: {kb_root}/scratch/{date}/{HHMMSS}_buffer.md

        Args:
            kb_root: Root directory for KB (default: build/dev)

        Returns:
            dict with path, entry_count, total_bytes, error
        """
        # Get all buffer entries under lock
        stats = self._buffer.get_stats()

        async with self._buffer._lock:
            entries = list(self._buffer._entries)

        if not entries:
            return {
                "path": "",
                "entry_count": 0,
                "total_bytes": 0,
                "error": "Buffer empty",
            }

        # Format as markdown
        content = self._format_buffer_markdown(entries, stats)

        # Write to KB
        now = datetime.now()
        date_dir = now.strftime("%Y-%m-%d")
        timestamp = now.strftime("%H%M%S")
        filename = f"{timestamp}_buffer.md"

        rel_path = f"scratch/{date_dir}/{filename}"
        full_path = Path(kb_root) / rel_path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(content, encoding="utf-8")

        logger.info(
            f"Exported buffer to {rel_path}: "
            f"{len(entries)} entries, {stats['current_bytes']} bytes"
        )

        return {
            "path": rel_path,
            "entry_count": len(entries),
            "total_bytes": stats["current_bytes"],
        }

    def _format_buffer_markdown(
        self, entries: list[BufferEntry], stats: dict[str, Any]
    ) -> str:
        """Format buffer entries as zettelkasten markdown.

        Args:
            entries: List of BufferEntry objects
            stats: Buffer statistics dict

        Returns:
            Markdown content string
        """
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

        # Group by role
        by_role: dict[str, list[BufferEntry]] = defaultdict(list)
        for entry in entries:
            by_role[entry.role.value].append(entry)

        for role, role_entries in by_role.items():
            lines.append(f"## {role.title()} ({len(role_entries)} entries)")
            lines.append("")
            for entry in role_entries:
                # Use author + story as heading if available
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
