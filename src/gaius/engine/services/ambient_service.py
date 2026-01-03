"""Ambient Computing Workload Service.

Manages ambient computing workload cycles that deliver continuous,
invisible, self-sustaining model activity. The system:

1. Maintains a baseline endpoint mix (orchestrator + fast + coding)
2. Executes standard tasks on each endpoint to verify health
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
import random
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any, AsyncIterator, Optional

from ..backends import ProcessStatus
from ..generated import gaius_service_pb2 as pb
from .ambient_buffer import AmbientBuffer, BufferEntry, BufferRole

if TYPE_CHECKING:
    from ..backends import BackendRouter
    from ..config import EngineConfig
    from .agenda_tracker import AgendaTracker
    from .orchestrator_service import OrchestratorService

logger = logging.getLogger(__name__)


class AmbientPhase(Enum):
    """Phases of an ambient computing cycle."""

    BASELINE_HEALTH = "baseline_health"
    BASELINE_WORKLOAD = "baseline_workload"
    FETCH_CONTENT = "fetch_content"  # New: fetch external content
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


# Standard tasks for each baseline endpoint
BASELINE_TASKS: dict[str, AmbientTask] = {
    "orchestrator": AmbientTask(
        endpoint="orchestrator",
        prompt="Route this request: 'Write a Python function'",
        expected_capability="routing",
        timeout_secs=10,
    ),
    "fast": AmbientTask(
        endpoint="fast",
        prompt="Explain what a hash table is in one sentence.",
        expected_capability="generation",
        timeout_secs=15,
    ),
    "coding": AmbientTask(
        endpoint="coding",
        prompt="Complete this function:\ndef fibonacci(n):\n    ",
        expected_capability="coding",
        timeout_secs=20,
    ),
}

DEFAULT_REASONING_TASK = AmbientTask(
    endpoint="reasoning",
    prompt="Analyze the trade-offs between microservices and monoliths for a startup.",
    expected_capability="reasoning",
    timeout_secs=120,
)

# Varied task pools for daemon mode
VARIED_BASELINE_TASKS: list[tuple[str, AmbientTask]] = [
    # Fast endpoint tasks
    ("fast", AmbientTask(
        endpoint="fast",
        prompt="Explain what a hash table is in one sentence.",
        expected_capability="generation",
        timeout_secs=15,
    )),
    ("fast", AmbientTask(
        endpoint="fast",
        prompt="What is the time complexity of binary search?",
        expected_capability="generation",
        timeout_secs=15,
    )),
    ("fast", AmbientTask(
        endpoint="fast",
        prompt="Define polymorphism in OOP.",
        expected_capability="generation",
        timeout_secs=15,
    )),
    ("fast", AmbientTask(
        endpoint="fast",
        prompt="Name three common design patterns.",
        expected_capability="generation",
        timeout_secs=15,
    )),
    # Coding endpoint tasks
    ("coding", AmbientTask(
        endpoint="coding",
        prompt="Complete this function:\ndef fibonacci(n):\n    ",
        expected_capability="coding",
        timeout_secs=20,
    )),
    ("coding", AmbientTask(
        endpoint="coding",
        prompt="Write a Python one-liner to reverse a string.",
        expected_capability="coding",
        timeout_secs=20,
    )),
    ("coding", AmbientTask(
        endpoint="coding",
        prompt="Implement a simple stack class in Python.",
        expected_capability="coding",
        timeout_secs=20,
    )),
    ("coding", AmbientTask(
        endpoint="coding",
        prompt="Write a function to check if a number is prime.",
        expected_capability="coding",
        timeout_secs=20,
    )),
    # Orchestrator tasks
    ("orchestrator", AmbientTask(
        endpoint="orchestrator",
        prompt="Route this request: 'Write a Python function'",
        expected_capability="routing",
        timeout_secs=10,
    )),
    ("orchestrator", AmbientTask(
        endpoint="orchestrator",
        prompt="Route this request: 'Explain recursion'",
        expected_capability="routing",
        timeout_secs=10,
    )),
    ("orchestrator", AmbientTask(
        endpoint="orchestrator",
        prompt="Route this request: 'Analyze the following code for bugs'",
        expected_capability="routing",
        timeout_secs=10,
    )),
]

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
    ):
        """Initialize ambient workload service.

        Args:
            config: Engine configuration
            orchestrator: Orchestrator service for endpoint management
            backend_router: Backend router for inference requests
        """
        self._config = config
        self._orchestrator = orchestrator
        self._backend_router = backend_router

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

        # Ambient buffer for content fetching (byte-sized FIFO)
        # Fetch and summarize are ALWAYS enabled - this is core ambient work
        buffer_cfg = config.ambient_buffer
        self._buffer = AmbientBuffer(max_bytes=buffer_cfg.buffer_max_bytes)

        logger.info(
            f"AmbientWorkloadService initialized with baseline: {self._baseline_endpoints}, "
            f"buffer: {buffer_cfg.buffer_max_bytes} bytes"
        )

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

        # Launch background task
        self._daemon_task = asyncio.create_task(
            self._daemon_loop(baseline_only),
            name="ambient-daemon",
        )

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

    async def _run_varied_cycle(self, baseline_only: bool) -> AsyncIterator[pb.AmbientPhaseEvent]:
        """Run a single cycle with varied task selection.

        Unlike run_cycle(), this selects random tasks from the varied pools.
        """
        start_time = time.time()

        # Phase 1: Health check
        yield self._make_event(
            pb.AMBIENT_PHASE_BASELINE_HEALTH,
            "Checking endpoint health",
            0.0,
        )

        health_results = await self._verify_baseline_health()
        healthy_count = sum(1 for h in health_results.values() if h)

        if healthy_count == 0:
            yield self._make_event(
                pb.AMBIENT_PHASE_ERROR,
                f"No healthy endpoints (0/{len(self._baseline_endpoints)})",
                0.0,
            )
            return

        yield self._make_event(
            pb.AMBIENT_PHASE_BASELINE_HEALTH,
            f"{healthy_count}/{len(self._baseline_endpoints)} healthy",
            1.0,
            {ep: "healthy" if h else "unhealthy" for ep, h in health_results.items()},
        )

        # Phase 2: Varied baseline workload
        yield self._make_event(
            pb.AMBIENT_PHASE_BASELINE_WORKLOAD,
            "Running baseline tasks",
            0.0,
        )

        # Select 2-4 random tasks from varied pool
        available_tasks = [
            (ep, task) for ep, task in VARIED_BASELINE_TASKS
            if health_results.get(ep, False)
        ]
        num_tasks = min(random.randint(2, 4), len(available_tasks))
        selected_tasks = random.sample(available_tasks, num_tasks) if available_tasks else []

        task_results = []
        for ep, task in selected_tasks:
            result = await self._execute_task(task)
            task_results.append(result)
            self._total_daemon_tasks += 1
            if result.success:
                self._successful_daemon_tasks += 1

        successful = sum(1 for r in task_results if r.success)
        yield self._make_event(
            pb.AMBIENT_PHASE_BASELINE_WORKLOAD,
            f"{successful}/{len(task_results)} tasks",
            1.0,
            {r.endpoint: f"{r.latency_ms}ms" for r in task_results if r.success},
        )

        # Phase 2.5: Fetch Content (ALWAYS - core ambient work)
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
        else:
            yield self._make_event(
                pb.AMBIENT_PHASE_FETCH_CONTENT,
                f"Fetch failed: {fetch_result.get('error', 'unknown')}",
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
        phase: int,
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

            # Phase 2: Baseline workload
            self._current_phase = AmbientPhase.BASELINE_WORKLOAD
            yield self._make_event(
                pb.AMBIENT_PHASE_BASELINE_WORKLOAD,
                "Running baseline workload tasks",
                0.0,
            )

            baseline_results = await self._run_baseline_workload(
                baseline_task_count,
                health_results,
            )

            for result in baseline_results:
                total_tasks += 1
                if result.success:
                    successful_tasks += 1
                    if result.endpoint not in endpoint_latencies:
                        endpoint_latencies[result.endpoint] = []
                    endpoint_latencies[result.endpoint].append(result.latency_ms)

            phases_completed = 2
            yield self._make_event(
                pb.AMBIENT_PHASE_BASELINE_WORKLOAD,
                f"Baseline workload complete ({successful_tasks}/{total_tasks} tasks)",
                1.0,
                {r.endpoint: f"{r.latency_ms}ms" for r in baseline_results if r.success},
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

        for endpoint in self._baseline_endpoints:
            try:
                status = await self._orchestrator.ensure_endpoint(endpoint)
                results[endpoint] = status.status == ProcessStatus.HEALTHY.value
            except Exception as e:
                logger.warning(f"Health check failed for {endpoint}: {e}")
                results[endpoint] = False

        return results

    async def _run_baseline_workload(
        self,
        task_count: int,
        health_results: dict[str, bool],
    ) -> list[TaskResult]:
        """Run standard tasks on healthy baseline endpoints.

        Args:
            task_count: Number of tasks per endpoint
            health_results: Health status from phase 1

        Returns:
            List of task results
        """
        results = []

        for endpoint, is_healthy in health_results.items():
            if not is_healthy:
                logger.info(f"Skipping unhealthy endpoint: {endpoint}")
                continue

            task = BASELINE_TASKS.get(endpoint)
            if not task:
                logger.warning(f"No baseline task defined for endpoint: {endpoint}")
                continue

            for i in range(task_count):
                result = await self._execute_task(task)
                results.append(result)

                if not result.success:
                    logger.warning(f"Task {i+1}/{task_count} failed for {endpoint}: {result.error}")

        return results

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
                    "newcomments": buffer_cfg.newcomments,
                    "max_items": buffer_cfg.max_items,
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

            # Use fast endpoint for summarization (lower latency)
            response = await asyncio.wait_for(
                self._backend_router.complete(
                    prompt=summarize_prompt,
                    agent_alias="fast",
                    max_tokens=buffer_cfg.summarize_max_tokens,
                    temperature=0.7,
                ),
                timeout=30,
            )

            latency_ms = int((time.time() - start_time) * 1000)

            if response.error:
                return {
                    "success": False,
                    "error": response.error,
                    "latency_ms": latency_ms,
                }

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
        """Evict baseline endpoints to make room for reasoning.

        Uses the orchestrator's workload management to handle eviction.
        Tracks endpoint transitions via AgendaTracker for incident tracking.

        Returns:
            Dict with success status and evicted endpoints
        """
        try:
            # Use begin_workload to request reasoning capability
            from ..workloads import WorkloadRequest, WorkloadType, JobPriority
            from gaius.models.registry import TaskType

            request = WorkloadRequest(
                workload_id=f"ambient-reasoning-{int(time.time())}",
                workload_type=WorkloadType.INFERENCE,
                required_capabilities=[TaskType.REASONING],
                priority=JobPriority.HIGH,
                estimated_duration_s=120,
                estimated_memory_mb=32000,  # ~32GB for reasoning model
                preemptible=False,
            )

            result = await self._orchestrator.begin_workload(request)

            response = {
                "success": result.success,
                "evicted": list(result.evicted_endpoints) if result.evicted_endpoints else [],
                "restore_plan": list(result.restore_plan) if result.restore_plan else [],
                "wait_time_ms": result.wait_time_ms,
                "workload_id": request.workload_id,
            }

            # Track eviction for AgendaTracker integration
            if result.success:
                self._current_workload_id = request.workload_id
                self._evicted_endpoints = list(result.evicted_endpoints) if result.evicted_endpoints else []

                # Record eviction transitions as POSITIVE control (orchestrated)
                # Note: ABSENT represents a stopped/non-running endpoint state
                if self._agenda_tracker and self._evicted_endpoints:
                    from ..resources.reconciliation import EndpointState
                    from ..incidents import ControlMode

                    for endpoint in self._evicted_endpoints:
                        try:
                            await self._agenda_tracker.on_endpoint_transition(
                                endpoint=endpoint,
                                from_state=EndpointState.HEALTHY,
                                to_state=EndpointState.ABSENT,  # ABSENT = not running
                                observed_control=ControlMode.POSITIVE,  # Orchestrated eviction
                            )
                            logger.debug(f"Recorded eviction transition for {endpoint}")
                        except Exception as e:
                            logger.warning(f"Failed to record eviction transition for {endpoint}: {e}")

            # Get the allocated reasoning endpoint for use in the reasoning task
            if result.success and result.allocated_endpoints:
                reasoning_alloc = result.allocated_endpoints.get(TaskType.REASONING)
                if reasoning_alloc:
                    response["reasoning_endpoint"] = reasoning_alloc.endpoint_name
                    response["reasoning_port"] = reasoning_alloc.port

            # Include error message from WorkloadResult if present
            if not result.success and result.error:
                response["error"] = result.error
            return response

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
        phase: int,
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
