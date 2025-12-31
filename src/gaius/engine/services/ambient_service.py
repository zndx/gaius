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
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Any, AsyncIterator, Optional

from ..backends import ProcessStatus
from ..proto import gaius_service_pb2 as pb

if TYPE_CHECKING:
    from ..backends import BackendRouter
    from ..config import EngineConfig
    from .orchestrator_service import OrchestratorService

logger = logging.getLogger(__name__)


class AmbientPhase(Enum):
    """Phases of an ambient computing cycle."""

    BASELINE_HEALTH = "baseline_health"
    BASELINE_WORKLOAD = "baseline_workload"
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

        logger.info(
            f"AmbientWorkloadService initialized with baseline: {self._baseline_endpoints}"
        )

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
    # Main Cycle Execution
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

    async def _execute_task(self, task: AmbientTask) -> TaskResult:
        """Execute a single ambient task.

        Args:
            task: Task to execute

        Returns:
            TaskResult with latency and success status
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

        Returns:
            Dict with restoration status
        """
        try:
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
