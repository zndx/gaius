"""Orchestrator service for GPU endpoint lifecycle management.

Wraps the GPUOrchestrator functionality and integrates with the
backend router for unified endpoint management.

BDD Alignment (swarm_evolution.feature):
- Start evolution daemon with '/evolve start' → clean start, endpoint management
- Evolution daemon monitors GPU idle state → health monitoring
- Orphaned vLLM processes should be cleaned up → cleanup_stale_processes

Yunikorn-Style Workload Management:
- Capability-based routing: requests declare capabilities, not endpoints
- Priority-based preemption: idle endpoints evicted for higher-priority work
- Makespan fulfillment: engine ensures work completes, then restores set points
"""

import asyncio
import logging
import os
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any, Optional

from ..backends import BackendRouter, OptillmController, ProcessStatus, VLLMController
from ..config import EngineConfig
from ..resources import ResourceManager

if TYPE_CHECKING:
    from gaius.models.registry import ModelSpec, TaskType
    from ..backends.vllm_controller import VLLMProcess
    from ..config import AgentConfig
    from ..phase_change import PhaseChangeObserver
    from ..scheduling.types import SchedulingTask, TransitionPlan
    from ..workloads import WorkloadRequest, WorkloadResult
    from .agenda_tracker import AgendaTracker

logger = logging.getLogger(__name__)


@dataclass
class EndpointStatus:
    """Status of an inference endpoint.

    Attributes:
        agent_alias: Agent this endpoint serves
        model: Model loaded
        port: Serving port
        gpu_ids: GPUs allocated
        status: Process status
        pid: Process ID if running
        started_at: When started
        requests_served: Number of requests handled
        startup_progress: Current startup progress (0-1)
        startup_message: Current startup status message
    """

    agent_alias: str
    model: str
    port: Optional[int]
    gpu_ids: list[int]
    status: str
    pid: Optional[int] = None
    started_at: Optional[datetime] = None
    requests_served: int = 0
    startup_progress: float = 0.0
    startup_message: str = ""


@dataclass
class CleanupResult:
    """Result of cleanup operation.

    Attributes:
        processes_found: Number of stale processes found
        processes_killed: Number killed
        pids_killed: List of PIDs that were killed
        cuda_cache_cleared: Whether CUDA cache was cleared
        errors: Any errors encountered
    """

    processes_found: int = 0
    processes_killed: int = 0
    pids_killed: list[int] = field(default_factory=list)
    cuda_cache_cleared: bool = False
    errors: list[str] = field(default_factory=list)


@dataclass
class EndpointActivity:
    """Track endpoint usage for preemption decisions.

    Yunikorn-style activity tracking to determine which endpoints
    are idle and can be evicted for higher-priority work.

    Attributes:
        endpoint_name: Name of the endpoint
        last_request_time: Unix timestamp of last request
        requests_in_flight: Number of active requests
        priority: Priority level of current workload
        capability: TaskType capability this endpoint provides
        model_id: Model being served
    """

    endpoint_name: str
    last_request_time: float = field(default_factory=time.time)
    requests_in_flight: int = 0
    priority: int = 2  # JobPriority.NORMAL.value
    capability: Optional[str] = None  # TaskType value
    model_id: str = ""

    @property
    def is_idle(self) -> bool:
        """Idle if no requests in 60 seconds and none in flight."""
        return (
            self.requests_in_flight == 0 and
            time.time() - self.last_request_time > 60.0
        )

    @property
    def idle_seconds(self) -> float:
        """Seconds since last request."""
        return time.time() - self.last_request_time


class OrchestratorService:
    """GPU endpoint orchestration service.

    Manages vLLM endpoint lifecycle with clean start support,
    health monitoring, and resource coordination.

    BDD Scenarios Supported:
    - Start evolution daemon with '/evolve start' (clean_start)
    - Evolution daemon monitors GPU idle state (get_gpu_utilization)
    - Orphaned vLLM processes should be cleaned up (cleanup_stale_processes)
    """

    def __init__(
        self,
        config: EngineConfig,
        resource_manager: ResourceManager,
        backend_router: BackendRouter,
    ):
        """Initialize orchestrator service.

        Args:
            config: Engine configuration
            resource_manager: Resource manager for GPU tracking
            backend_router: Backend router for inference
        """
        self.config = config
        self.resource_manager = resource_manager
        self.backend_router = backend_router

        # Access controllers through backend router
        self._vllm = backend_router.vllm
        self._optillm: Optional[OptillmController] = backend_router.optillm

        # Health monitoring
        self._health_task: Optional[asyncio.Task] = None
        self._running = False
        self._health_interval = config.health_interval_ms / 1000

        # GPU utilization cache (updated by health checks)
        self._gpu_utilization: dict[int, float] = {}
        self._last_health_check: Optional[datetime] = None

        # Auto-restart configuration
        self._auto_restart_enabled = getattr(
            config.startup, "auto_restart_failed", True
        )
        self._max_restart_attempts = getattr(
            config.startup, "max_restart_attempts", 3
        )
        # Track restart attempts per endpoint
        self._restart_attempts: dict[str, int] = {}

        # Stuck state detection (AIOps autonomous health loop)
        self._stuck_starting_timeout = 300  # 5 minutes
        self._stuck_stopping_timeout = 120  # 2 minutes
        self._stuck_detections: dict[str, dict] = {}  # endpoint -> {detected_at, elapsed}

        # Capability-based endpoint tracking (Yunikorn-style)
        # Maps TaskType.value -> list of endpoint names that provide that capability
        self._capability_map: dict[str, list[str]] = {}
        # Maps endpoint name -> EndpointActivity
        self._endpoint_activity: dict[str, EndpointActivity] = {}
        # Active workloads being tracked
        self._active_workloads: dict[str, Any] = {}  # workload_id -> ActiveWorkload

        # CLT subprocess capability (managed separately from vLLM endpoints)
        # Stores (CLTService, allocated_gpu_id) when CLT is active
        self._clt_capability: Optional[tuple[Any, int]] = None

        # Agenda-centric incident tracking
        # Wired via set_agenda_tracker() after server initialization
        self._agenda_tracker: Optional["AgendaTracker"] = None

        # Phase Change Observer for resilient workload coordination
        # Lazily initialized to avoid circular imports
        self._phase_observer: Optional["PhaseChangeObserver"] = None

        logger.info("OrchestratorService initialized")

    async def start(self) -> None:
        """Start the orchestrator service."""
        if self._running:
            return

        self._running = True

        # Start health monitoring loop
        self._health_task = asyncio.create_task(self._health_loop())

        logger.info("OrchestratorService started")

    async def stop(self) -> None:
        """Stop the orchestrator service."""
        if not self._running:
            return

        self._running = False

        # Cancel health task
        if self._health_task:
            self._health_task.cancel()
            try:
                await self._health_task
            except asyncio.CancelledError:
                pass

        logger.info("OrchestratorService stopped")

    def set_agenda_tracker(self, tracker: "AgendaTracker") -> None:
        """Set the agenda tracker for workload incident tracking.

        This enables agenda-centric incident tracking where:
        - Agenda (scheduled capability phases) is the unit of health
        - Makespan fulfillment is the success metric
        - Positive control is required for resolution

        Args:
            tracker: AgendaTracker instance
        """
        self._agenda_tracker = tracker
        logger.info("AgendaTracker wired to OrchestratorService")

    # ─────────────────────────────────────────────────────────────────────────
    # Endpoint Management
    # ─────────────────────────────────────────────────────────────────────────

    async def ensure_endpoint(self, agent_alias: str) -> EndpointStatus:
        """Ensure endpoint is running, starting if needed and resources available.

        This is the primary method for agent-first architecture. CLI and agents
        call this to ensure an endpoint is available before making requests.

        Args:
            agent_alias: Agent identifier

        Returns:
            EndpointStatus with healthy=True if ready, or error info if not

        Raises:
            ValueError: If agent not in config
        """
        if agent_alias not in self.config.agents:
            raise ValueError(f"Unknown agent: {agent_alias}")

        agent_config = self.config.agents[agent_alias]
        backend = agent_config.backend.lower()

        # For optillm-backed agents, no dedicated endpoint needed
        if backend == "optillm":
            return EndpointStatus(
                agent_alias=agent_alias,
                model=agent_config.model,
                port=None,
                gpu_ids=[],
                status="optillm",  # Uses shared optillm, always available
            )

        # ColPali backend for multi-vector embeddings (ColNomic)
        if backend == "colpali":
            # Check if ColPali endpoint already exists
            from ..backends.colpali_controller import get_colpali_controller
            controller = get_colpali_controller()
            endpoints = controller.list_endpoints()
            for ep in endpoints:
                if ep and ep.get("status") == "ready":
                    return EndpointStatus(
                        agent_alias=agent_alias,
                        model=agent_config.model,
                        port=None,  # ColPali doesn't use HTTP
                        gpu_ids=ep.get("gpu_ids", []),
                        status="healthy",
                    )
            # Not loaded yet, start it
            return await self._start_colpali_endpoint(agent_alias, agent_config)

        # Note: sentence-transformers backend is deprecated.
        # Use backend = "vllm" with endpoint.task = "embed" instead.
        # vLLM handles embedding models directly with --task embed flag.

        # Check if already healthy
        existing = self.get_endpoint_status(agent_alias)
        if existing and existing.status == "healthy":
            logger.debug(f"Endpoint {agent_alias} already healthy")
            return existing

        # Check resource availability
        required_gpus = agent_config.resources.gpus
        free_gpus = self.resource_manager.get_free_gpus()

        if len(free_gpus) < required_gpus:
            # Not enough GPUs - return informative status
            return EndpointStatus(
                agent_alias=agent_alias,
                model=agent_config.model,
                port=None,
                gpu_ids=[],
                status="insufficient_resources",
                startup_message=f"Need {required_gpus} GPUs, only {len(free_gpus)} free",
            )

        # Check for contiguous GPUs if tensor_parallel > 1
        if required_gpus > 1 and self.resource_manager.prefer_contiguous:
            contiguous = self._find_contiguous_gpus(free_gpus, required_gpus)
            if not contiguous:
                return EndpointStatus(
                    agent_alias=agent_alias,
                    model=agent_config.model,
                    port=None,
                    gpu_ids=[],
                    status="no_contiguous_gpus",
                    startup_message=f"Need {required_gpus} contiguous GPUs for tensor parallel",
                )

        # Start the endpoint
        logger.info(f"ensure_endpoint: starting {agent_alias} ({required_gpus} GPUs)")
        return await self.start_endpoint(agent_alias)

    def _find_contiguous_gpus(self, free_gpus: list[int], count: int) -> list[int]:
        """Find contiguous GPUs from free list.

        Args:
            free_gpus: Available GPU IDs
            count: Number needed

        Returns:
            List of contiguous GPU IDs, or empty if not found
        """
        free_set = set(free_gpus)
        for start in free_gpus:
            contiguous = []
            for i in range(count):
                if (start + i) in free_set:
                    contiguous.append(start + i)
                else:
                    break
            if len(contiguous) == count:
                return contiguous
        return []

    async def start_endpoint(self, agent_alias: str) -> EndpointStatus:
        """Start an inference endpoint for an agent.

        Args:
            agent_alias: Agent identifier

        Returns:
            EndpointStatus with startup state
        """
        if agent_alias not in self.config.agents:
            raise ValueError(f"Unknown agent: {agent_alias}")

        agent_config = self.config.agents[agent_alias]
        backend = agent_config.backend.lower()

        # optillm agents use shared optillm, no dedicated endpoint
        if backend == "optillm":
            return EndpointStatus(
                agent_alias=agent_alias,
                model=agent_config.model,
                port=None,
                gpu_ids=[],
                status="optillm",  # Uses optillm, no dedicated endpoint
            )

        # ColPali backend for multi-vector embeddings (ColNomic)
        if backend == "colpali":
            return await self._start_colpali_endpoint(agent_alias, agent_config)

        # Note: sentence-transformers backend is deprecated.
        # Use backend = "vllm" with endpoint.task = "embed" instead.

        # Start vLLM endpoint
        proc = await self._vllm.start_endpoint(agent_alias, agent_config)

        return EndpointStatus(
            agent_alias=agent_alias,
            model=proc.model,
            port=proc.port,
            gpu_ids=proc.gpu_ids,
            status=proc.status.value,
            pid=proc.pid,
            started_at=proc.started_at,
        )

    async def stop_endpoint(self, agent_alias: str) -> bool:
        """Stop an inference endpoint.

        Args:
            agent_alias: Agent identifier

        Returns:
            True if stopped successfully
        """
        return await self._vllm.stop_endpoint(agent_alias)

    async def restart_endpoint(self, agent_alias: str) -> EndpointStatus:
        """Restart an inference endpoint.

        Args:
            agent_alias: Agent identifier

        Returns:
            EndpointStatus after restart
        """
        await self.stop_endpoint(agent_alias)
        await asyncio.sleep(2)  # Brief cooldown
        return await self.start_endpoint(agent_alias)

    async def _start_embedding_endpoint(
        self,
        agent_alias: str,
        agent_config: "AgentConfig",
    ) -> EndpointStatus:
        """Start a sentence-transformers embedding endpoint.

        Uses the EmbeddingController to load the model on GPU.

        Args:
            agent_alias: Agent identifier
            agent_config: Agent configuration

        Returns:
            EndpointStatus with startup state
        """
        from ..backends.embedding_controller import get_embedding_controller
        from gaius.models.registry import ModelSpec

        try:
            controller = get_embedding_controller()

            # Create ModelSpec from agent config
            model_spec = ModelSpec(
                model_id=agent_config.model,
                name=agent_alias,
                provider="sentence-transformers",
            )

            # Allocate GPU for embedding model
            required_gpus = agent_config.resources.gpus
            free_gpus = self.resource_manager.get_free_gpus()

            if len(free_gpus) < required_gpus:
                return EndpointStatus(
                    agent_alias=agent_alias,
                    model=agent_config.model,
                    port=None,
                    gpu_ids=[],
                    status="insufficient_resources",
                    startup_message=f"Need {required_gpus} GPUs, only {len(free_gpus)} free",
                )

            gpu_ids = free_gpus[:required_gpus]

            # Start embedding endpoint
            endpoint = await controller.start_embedding_endpoint(
                model_spec=model_spec,
                gpu_ids=gpu_ids,
                endpoint_name=agent_alias,
            )

            # Track the allocation
            self.resource_manager.allocate(agent_alias, agent_config)

            return EndpointStatus(
                agent_alias=agent_alias,
                model=agent_config.model,
                port=None,  # Embedding endpoints don't use HTTP
                gpu_ids=gpu_ids,
                status="healthy" if endpoint.status.value == "ready" else endpoint.status.value,
                startup_message=f"Embedding model {agent_config.model} loaded",
            )

        except Exception as e:
            logger.error(f"Failed to start embedding endpoint {agent_alias}: {e}")
            return EndpointStatus(
                agent_alias=agent_alias,
                model=agent_config.model,
                port=None,
                gpu_ids=[],
                status="failed",
                startup_message=f"Failed: {e}",
            )

    async def _start_colpali_endpoint(
        self,
        agent_alias: str,
        agent_config: "AgentConfig",
    ) -> EndpointStatus:
        """Start a ColPali multi-vector embedding endpoint.

        Uses the ColPaliController to load ColNomic or other ColPali models.
        ColPali produces multi-vector embeddings (one per token) for
        late-interaction retrieval patterns.

        Args:
            agent_alias: Agent identifier
            agent_config: Agent configuration

        Returns:
            EndpointStatus with startup state
        """
        from ..backends.colpali_controller import get_colpali_controller
        from gaius.models.registry import ModelSpec

        try:
            controller = get_colpali_controller()

            # Create ModelSpec from agent config
            model_spec = ModelSpec(
                model_id=agent_config.model,
                name=agent_alias,
                provider="colpali",
            )

            # Allocate GPU for ColPali model
            required_gpus = agent_config.resources.gpus
            free_gpus = self.resource_manager.get_free_gpus()

            if len(free_gpus) < required_gpus:
                return EndpointStatus(
                    agent_alias=agent_alias,
                    model=agent_config.model,
                    port=None,
                    gpu_ids=[],
                    status="insufficient_resources",
                    startup_message=f"Need {required_gpus} GPUs, only {len(free_gpus)} free",
                )

            gpu_ids = free_gpus[:required_gpus]

            logger.info(f"Starting ColPali endpoint {agent_alias} on GPUs {gpu_ids}")

            # Start ColPali endpoint
            endpoint = await controller.start_colpali_endpoint(
                model_spec=model_spec,
                gpu_ids=gpu_ids,
                endpoint_name=agent_alias,
            )

            # Track the allocation
            self.resource_manager.allocate(agent_alias, agent_config)

            return EndpointStatus(
                agent_alias=agent_alias,
                model=agent_config.model,
                port=None,  # ColPali endpoints don't use HTTP
                gpu_ids=gpu_ids,
                status="healthy" if endpoint.status.value == "ready" else endpoint.status.value,
                startup_message=f"ColPali model {agent_config.model} loaded",
            )

        except Exception as e:
            logger.error(f"Failed to start ColPali endpoint {agent_alias}: {e}")
            return EndpointStatus(
                agent_alias=agent_alias,
                model=agent_config.model,
                port=None,
                gpu_ids=[],
                status="failed",
                startup_message=f"Failed: {e}",
            )

    def get_endpoint_status(self, agent_alias: str) -> Optional[EndpointStatus]:
        """Get status of a specific endpoint.

        Args:
            agent_alias: Agent identifier

        Returns:
            EndpointStatus if exists
        """
        # Check vLLM processes first
        proc = self._vllm.get_process(agent_alias)
        if proc:
            # Get startup progress
            message, progress = self._vllm.get_startup_progress(agent_alias)

            return EndpointStatus(
                agent_alias=agent_alias,
                model=proc.model,
                port=proc.port,
                gpu_ids=proc.gpu_ids,
                status=proc.status.value,
                pid=proc.pid,
                started_at=proc.started_at,
                requests_served=proc.requests_served,
                startup_progress=progress,
                startup_message=message,
            )

        # Check ColPali endpoints if this is a colpali-backed agent
        if agent_alias in self.config.agents:
            agent_config = self.config.agents[agent_alias]
            if agent_config.backend.lower() == "colpali":
                try:
                    from ..backends.colpali_controller import get_colpali_controller
                    controller = get_colpali_controller()
                    info = controller.get_endpoint_info(agent_alias)
                    if info:
                        return EndpointStatus(
                            agent_alias=agent_alias,
                            model=info.get("model", agent_config.model),
                            port=None,
                            gpu_ids=info.get("gpu_ids", []),
                            status="healthy" if info.get("status") == "ready" else info.get("status", "unknown"),
                            requests_served=info.get("requests_served", 0),
                        )
                except Exception:
                    pass

        return None

    def get_all_endpoint_status(self) -> dict[str, EndpointStatus]:
        """Get status of all endpoints.

        Returns:
            Dict mapping agent alias to status
        """
        result = {}
        for alias in self._vllm._processes:
            status = self.get_endpoint_status(alias)
            if status:
                result[alias] = status
        return result

    def get_endpoint_logs(self, agent_alias: str, lines: int = 50) -> list[str]:
        """Get recent logs from an endpoint.

        Args:
            agent_alias: Agent identifier
            lines: Number of lines to return

        Returns:
            List of log lines
        """
        return self._vllm.get_recent_logs(agent_alias, lines)

    # ─────────────────────────────────────────────────────────────────────────
    # Phase Change Pattern (Resilient Workload Coordination)
    # ─────────────────────────────────────────────────────────────────────────

    def _get_phase_observer(self) -> "PhaseChangeObserver":
        """Get or create the PhaseChangeObserver (lazy init).

        Returns:
            PhaseChangeObserver instance
        """
        if self._phase_observer is None:
            from ..phase_change import PhaseChangeObserver
            self._phase_observer = PhaseChangeObserver(self)
        return self._phase_observer

    async def get_endpoint_status_async(self, agent_alias: str) -> str:
        """Get endpoint status string (async version for PhaseChangeObserver).

        Args:
            agent_alias: Agent identifier

        Returns:
            Status string like "PROCESS_STATUS_HEALTHY"
        """
        status = self.get_endpoint_status(agent_alias)
        if status:
            # Normalize to proto-style status string
            status_str = status.status
            if not status_str.startswith("PROCESS_STATUS_"):
                status_str = f"PROCESS_STATUS_{status_str.upper()}"
            return status_str
        return "PROCESS_STATUS_STOPPED"

    async def phase_change(
        self,
        change_type: str,
        target_endpoint: str,
        await_healthy: bool = True,
        timeout_s: float = 120.0,
    ) -> dict[str, Any]:
        """Execute a phase change with convergence waiting.

        A Phase Change occurs when the system transitions between operational
        modes (e.g., loading ColNomic for vector search). This method waits
        for the target endpoint to reach HEALTHY status before returning.

        Design Philosophy: "Premature optimization is the root of all evil."
        The solution prioritizes resilience over speed by awaiting positive
        confirmation of HEALTHY status before proceeding.

        Args:
            change_type: Type of phase change (colnomic_load, instruct_restore, etc.)
            target_endpoint: Endpoint name to ensure healthy
            await_healthy: Whether to block until HEALTHY confirmed (default: True)
            timeout_s: Maximum seconds to wait for convergence (default: 120)

        Returns:
            Dict with keys:
                - converged: bool - Whether endpoint reached HEALTHY
                - duration_ms: int - Time taken for phase change
                - endpoint_status: str - Final endpoint status
                - otel_trace_id: str - Trace ID for debugging
                - error: Optional[str] - Error message if failed

        Guru Codes:
            #PC.00000001.TIMEOUT - Phase change timeout
            #PC.00000002.FAILED - Phase change to FAILED status
        """
        from ..phase_change import PhaseChangeType

        started = time.time()
        observer = self._get_phase_observer()

        try:
            change_type_enum = PhaseChangeType(change_type)
        except ValueError:
            return {
                "converged": False,
                "duration_ms": 0,
                "endpoint_status": "UNKNOWN",
                "error": f"Unknown change_type: {change_type}",
            }

        try:
            if await_healthy:
                # Use PhaseChangeObserver to wait for convergence
                event = await observer.await_phase_change(
                    change_type=change_type_enum,
                    target_endpoint=target_endpoint,
                    timeout_s=timeout_s,
                )

                return {
                    "converged": event.status.value == "converged",
                    "duration_ms": event.duration_ms or 0,
                    "endpoint_status": await self.get_endpoint_status_async(target_endpoint),
                    "otel_trace_id": event.otel_trace_id,
                    "error": event.error_message,
                }
            else:
                # Non-blocking: just initiate the change
                await self.ensure_endpoint(target_endpoint)
                return {
                    "converged": False,  # Not awaited
                    "duration_ms": int((time.time() - started) * 1000),
                    "endpoint_status": await self.get_endpoint_status_async(target_endpoint),
                }

        except asyncio.TimeoutError:
            return {
                "converged": False,
                "duration_ms": int((time.time() - started) * 1000),
                "endpoint_status": "PROCESS_STATUS_TIMEOUT",
                "error": f"Phase change timed out after {timeout_s}s (#PC.00000001.TIMEOUT)",
            }
        except Exception as e:
            logger.exception("Phase change failed: %s", e)
            return {
                "converged": False,
                "duration_ms": int((time.time() - started) * 1000),
                "endpoint_status": "PROCESS_STATUS_FAILED",
                "error": f"Phase change error: {e} (#PC.00000002.FAILED)",
            }

    def get_phase_change_profiles(self) -> dict[str, dict]:
        """Get accumulated phase change timing profiles.

        Returns:
            Dict mapping change_type to profile statistics
        """
        return self._get_phase_observer().get_profiles()

    def get_active_phase_changes(self) -> list[dict]:
        """Get currently active phase changes.

        Returns:
            List of active phase change event dictionaries
        """
        return self._get_phase_observer().get_active_changes()

    # ─────────────────────────────────────────────────────────────────────────
    # Capability-Based Endpoint Management (Yunikorn-Style)
    # ─────────────────────────────────────────────────────────────────────────

    async def ensure_capability(
        self,
        task_type: "TaskType",
        priority: int = 2,  # JobPriority.NORMAL.value
    ) -> EndpointStatus:
        """Ensure an endpoint with the required capability is running.

        Yunikorn-style capability routing: requests declare what capability
        they need, not which specific endpoint. The orchestrator finds or
        starts an appropriate endpoint.

        If no endpoint with this capability is running:
        1. Find best model for task_type from registry
        2. Check if resources available
        3. If not, evict idle endpoints (priority-based)
        4. Start the endpoint
        5. Register capability mapping

        Args:
            task_type: TaskType capability needed (e.g., TEXT_EMBEDDING)
            priority: Request priority for preemption decisions

        Returns:
            EndpointStatus with the endpoint providing this capability
        """
        from gaius.models.registry import get_model_registry

        capability_key = task_type.value

        # Check if we already have an endpoint for this capability
        existing_endpoint = self.get_endpoint_for_capability(task_type)
        if existing_endpoint:
            status = self.get_endpoint_status(existing_endpoint)
            if status and status.status == "healthy":
                logger.debug(f"Reusing existing endpoint {existing_endpoint} for {capability_key}")
                return status

        # Find best model for this capability
        registry = get_model_registry()
        model_spec = registry.get_for_task(task_type, require_local=True)

        if not model_spec:
            return EndpointStatus(
                agent_alias="",
                model="",
                port=None,
                gpu_ids=[],
                status="no_model",
                startup_message=f"No model available for capability: {capability_key}",
            )

        # Check resource requirements
        requirements = model_spec.get_resource_requirements()
        free_gpus = self.resource_manager.get_free_gpus()

        if len(free_gpus) < requirements.num_gpus:
            # Try to evict idle endpoints to make room
            evicted = await self._find_and_evict_for_resources(
                required_gpus=requirements.num_gpus,
                required_memory_mb=requirements.memory_mb,
                requesting_priority=priority,
            )
            if not evicted:
                return EndpointStatus(
                    agent_alias="",
                    model=model_spec.model_id,
                    port=None,
                    gpu_ids=[],
                    status="insufficient_resources",
                    startup_message=f"Need {requirements.num_gpus} GPUs, only {len(free_gpus)} free",
                )
            # Re-check free GPUs after eviction
            free_gpus = self.resource_manager.get_free_gpus()

        # Create a dynamic endpoint name based on capability
        endpoint_name = f"cap_{capability_key}"

        # Start the endpoint
        logger.info(f"Starting endpoint {endpoint_name} for capability {capability_key}")
        status = await self._start_capability_endpoint(
            endpoint_name=endpoint_name,
            model_spec=model_spec,
            task_type=task_type,
            gpus=free_gpus[:requirements.num_gpus],
        )

        # Register capability mapping
        if status.status == "healthy" or status.status == "starting":
            self._register_capability(capability_key, endpoint_name, model_spec.model_id)

        return status

    def get_endpoint_for_capability(self, task_type: "TaskType") -> Optional[str]:
        """Get running endpoint that provides capability, or None.

        Args:
            task_type: The TaskType capability needed

        Returns:
            Endpoint name if one exists, None otherwise
        """
        capability_key = task_type.value
        endpoints = self._capability_map.get(capability_key, [])

        # Find first healthy endpoint
        for endpoint_name in endpoints:
            status = self.get_endpoint_status(endpoint_name)
            if status and status.status == "healthy":
                return endpoint_name

        return None

    def _register_capability(
        self,
        capability_key: str,
        endpoint_name: str,
        model_id: str,
    ) -> None:
        """Register an endpoint as providing a capability.

        Args:
            capability_key: TaskType.value
            endpoint_name: Name of the endpoint
            model_id: Model being served
        """
        if capability_key not in self._capability_map:
            self._capability_map[capability_key] = []

        if endpoint_name not in self._capability_map[capability_key]:
            self._capability_map[capability_key].append(endpoint_name)

        # Track activity
        self._endpoint_activity[endpoint_name] = EndpointActivity(
            endpoint_name=endpoint_name,
            capability=capability_key,
            model_id=model_id,
        )

        logger.info(f"Registered {endpoint_name} for capability {capability_key}")

    def _unregister_capability(self, endpoint_name: str) -> None:
        """Unregister an endpoint from all capability mappings.

        Args:
            endpoint_name: Name of the endpoint to unregister
        """
        for capability_key, endpoints in self._capability_map.items():
            if endpoint_name in endpoints:
                endpoints.remove(endpoint_name)

        if endpoint_name in self._endpoint_activity:
            del self._endpoint_activity[endpoint_name]

        logger.info(f"Unregistered endpoint {endpoint_name}")

    async def _start_capability_endpoint(
        self,
        endpoint_name: str,
        model_spec: "ModelSpec",
        task_type: "TaskType",
        gpus: list[int],
    ) -> EndpointStatus:
        """Start an endpoint for a capability.

        Args:
            endpoint_name: Name for the endpoint
            model_spec: Model specification
            task_type: Capability this provides
            gpus: GPU IDs to use

        Returns:
            EndpointStatus
        """
        from gaius.models.registry import ModelSpec

        # For embedding models, we need special handling (Phase 5)
        # For now, check if it's a vLLM-backed model
        if model_spec.provider == "vllm" and model_spec.vllm_config:
            # Create a temporary agent config for the endpoint
            port = self._find_available_port()
            cmd_str, env = model_spec.serve_command(port=port, gpus=gpus)

            # serve_command returns a string; split into list for subprocess
            import shlex
            cmd = shlex.split(cmd_str)

            # Start via vLLM controller
            proc = await self._vllm.start_model(
                endpoint_name=endpoint_name,
                model_id=model_spec.model_id,
                port=port,
                gpu_ids=gpus,
                serve_command=cmd,
                env_vars=env,
            )

            return EndpointStatus(
                agent_alias=endpoint_name,
                model=model_spec.model_id,
                port=port,
                gpu_ids=gpus,
                status=proc.status.value if proc else "failed",
                pid=proc.pid if proc else None,
            )
        elif model_spec.provider == "clt":
            # CLT subprocess-based capability
            # Uses a subprocess worker with isolated GPU (not vLLM)
            return await self._start_clt_capability(
                endpoint_name=endpoint_name,
                model_spec=model_spec,
                gpu=gpus[0] if gpus else 0,
            )
        else:
            # Non-vLLM model (embedding, API, etc.)
            # Use the embedding controller
            from ..backends.embedding_controller import get_embedding_controller

            try:
                controller = get_embedding_controller()
                endpoint = await controller.start_embedding_endpoint(
                    model_spec=model_spec,
                    gpu_ids=gpus,
                    endpoint_name=endpoint_name,
                )

                return EndpointStatus(
                    agent_alias=endpoint_name,
                    model=model_spec.model_id,
                    port=None,  # Embeddings don't use HTTP ports
                    gpu_ids=gpus,
                    status="healthy" if endpoint.status.value == "ready" else endpoint.status.value,
                    startup_message=f"Embedding model {model_spec.model_id} loaded",
                )
            except Exception as e:
                logger.error(f"Failed to start embedding endpoint: {e}")
                return EndpointStatus(
                    agent_alias=endpoint_name,
                    model=model_spec.model_id,
                    port=None,
                    gpu_ids=[],
                    status="failed",
                    startup_message=f"Failed to load embedding model: {e}",
                )

    def _is_port_free_on_system(self, port: int) -> bool:
        """Check if a port is free on the system (not just in our tracking).

        This prevents conflicts with external processes (kubectl port-forwards,
        other services, etc.) that may occupy ports in our allocation range.
        """
        import socket

        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                sock.bind(("0.0.0.0", port))
                return True
        except OSError:
            return False

    def _find_available_port(self, start: int = 8080, end: int = 8095) -> int:
        """Find an available port for a new endpoint.

        Checks both internal tracking AND system availability to prevent
        conflicts with external processes.

        Args:
            start: Start of port range
            end: End of port range

        Returns:
            Available port number
        """
        used_ports = set()
        for proc in self._vllm._processes.values():
            if proc.port:
                used_ports.add(proc.port)

        for port in range(start, end + 1):
            if port not in used_ports and self._is_port_free_on_system(port):
                return port

        raise RuntimeError(
            f"No available ports in range {start}-{end}. "
            f"Used by vLLM: {sorted(used_ports)}"
        )

    async def _start_clt_capability(
        self,
        endpoint_name: str,
        model_spec: "ModelSpec",
        gpu: int,
    ) -> EndpointStatus:
        """Start CLT subprocess capability.

        CLT runs as a subprocess with isolated GPU (not vLLM). The orchestrator
        manages the lifecycle and GPU allocation.

        Args:
            endpoint_name: Name for the capability endpoint
            model_spec: CLT model specification
            gpu: GPU index to use

        Returns:
            EndpointStatus with CLT capability info
        """
        from .clt_service import CLTService
        from ..resources.allocations import GPUAllocation, AllocationState

        logger.info(f"Starting CLT capability on GPU {gpu}")

        try:
            # Create CLT service with orchestrator-assigned GPU
            clt_service = CLTService(
                model_name="qwen3-1.7b",
                gpu_index=gpu,
            )

            # Pre-load the model (starts subprocess worker)
            clt_service.ensure_loaded()

            # Track the CLT capability
            self._clt_capability = (clt_service, gpu)

            # Register GPU allocation with ResourceManager
            allocation = GPUAllocation(
                agent_alias="clt",
                model=model_spec.model_id,
                gpu_ids=[gpu],
                vram_reserved_gb=6.0,  # CLT uses ~6GB
                state=AllocationState.ACTIVE,
            )
            self.resource_manager.allocations["clt"] = allocation

            return EndpointStatus(
                agent_alias=endpoint_name,
                model=model_spec.model_id,
                port=None,  # CLT doesn't use HTTP port
                gpu_ids=[gpu],
                status="healthy",
                pid=clt_service._worker.pid if clt_service._worker else None,
                startup_message=f"CLT loaded on GPU {gpu}",
            )
        except Exception as e:
            logger.error(f"Failed to start CLT capability: {e}")
            return EndpointStatus(
                agent_alias=endpoint_name,
                model=model_spec.model_id,
                port=None,
                gpu_ids=[],
                status="failed",
                startup_message=f"CLT startup failed: {e}",
            )

    def stop_clt_capability(self) -> None:
        """Stop CLT capability and release GPU.

        Called when CLT workload completes to free resources.
        """
        if self._clt_capability is None:
            return

        clt_service, gpu = self._clt_capability

        try:
            clt_service.unload()
            logger.info(f"CLT capability stopped, releasing GPU {gpu}")
        except Exception as e:
            logger.warning(f"Error stopping CLT: {e}")
        finally:
            # Release GPU allocation via ResourceManager
            self.resource_manager.release("clt")
            self._clt_capability = None

    def get_clt_service(self) -> Optional[Any]:
        """Get active CLT service if one is running.

        Returns:
            CLTService instance or None
        """
        if self._clt_capability:
            return self._clt_capability[0]
        return None

    def _build_current_scheduling_tasks(self) -> list["SchedulingTask"]:
        """Build SchedulingTasks from currently running endpoints.

        Returns:
            List of SchedulingTask objects representing current GPU allocations
        """
        from ..scheduling import SchedulingTask

        tasks = []

        # Get all running vLLM processes
        for proc_name, proc in self._vllm._processes.items():
            if proc.status.value not in ("healthy", "starting"):
                continue

            # Get activity info if tracked
            activity = self._endpoint_activity.get(proc_name)
            capability = activity.capability if activity else None
            priority = activity.priority if activity else 2  # NORMAL

            tasks.append(
                SchedulingTask(
                    task_id=proc_name,
                    endpoint_name=proc_name,
                    model_id=proc.model,
                    required_gpus=len(proc.gpu_ids),
                    salience=float(priority),
                    capability=capability,
                    prefer_contiguous=len(proc.gpu_ids) > 1,
                    fixed_gpu_ids=list(proc.gpu_ids),
                    is_current=True,
                )
            )

        return tasks

    def _build_target_scheduling_tasks(
        self,
        request: "WorkloadRequest",
        current_tasks: list["SchedulingTask"],
    ) -> list["SchedulingTask"]:
        """Build target SchedulingTasks from a workload request.

        Args:
            request: WorkloadRequest with required capabilities
            current_tasks: Currently running tasks

        Returns:
            List of SchedulingTask for desired target state
        """
        from gaius.models.registry import get_model_registry
        from ..scheduling import SchedulingTask

        registry = get_model_registry()
        target_tasks = []

        # Check which capabilities we need that aren't already running
        current_capabilities = {
            t.capability for t in current_tasks if t.capability
        }

        for task_type in request.required_capabilities:
            capability_key = task_type.value

            # If we already have this capability, keep it
            for task in current_tasks:
                if task.capability == capability_key:
                    target_tasks.append(task)
                    break
            else:
                # Need to start a new endpoint for this capability
                model_spec = registry.get_for_task(task_type, require_local=True)
                if not model_spec:
                    logger.warning(f"No model for capability {capability_key}")
                    continue

                requirements = model_spec.get_resource_requirements()

                target_tasks.append(
                    SchedulingTask(
                        task_id=f"cap_{capability_key}",
                        endpoint_name=f"cap_{capability_key}",
                        model_id=model_spec.model_id,
                        required_gpus=requirements.num_gpus,
                        salience=float(request.priority.value),
                        capability=capability_key,
                        prefer_contiguous=requirements.num_gpus > 1,
                        is_current=False,
                    )
                )

        return target_tasks

    async def _execute_transition_plan(
        self,
        plan: "TransitionPlan",
    ) -> bool:
        """Execute a transition plan from the scheduler.

        Executes stops in parallel, then starts in dependency order.

        Args:
            plan: TransitionPlan from MakespanScheduler

        Returns:
            True if all steps succeeded
        """
        from ..scheduling import TransitionType

        # Execute stop steps (can run in parallel)
        stop_tasks = []
        for step in plan.steps:
            if step.transition_type == TransitionType.STOP_ENDPOINT:
                stop_tasks.append(self.stop_endpoint(step.endpoint_name))

        if stop_tasks:
            logger.info(f"Stopping {len(stop_tasks)} endpoints in parallel")
            results = await asyncio.gather(*stop_tasks, return_exceptions=True)
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    logger.error(f"Failed to stop endpoint: {result}")

        # Wait for GPU memory release
        await asyncio.sleep(2)

        # Execute start steps in order (respecting dependencies)
        completed_steps: set[int] = {
            s.step_id for s in plan.steps
            if s.transition_type == TransitionType.STOP_ENDPOINT
        }

        start_steps = [
            s for s in plan.steps
            if s.transition_type == TransitionType.START_ENDPOINT
        ]

        for step in start_steps:
            # Wait for dependencies
            if not all(d in completed_steps for d in step.depends_on):
                logger.warning(f"Step {step.step_id} has unmet dependencies")

            logger.info(
                f"Starting {step.endpoint_name} on GPUs {step.gpu_ids}"
            )

            # Start the endpoint with the scheduled GPU assignment
            status = await self._start_scheduled_endpoint(
                endpoint_name=step.endpoint_name,
                gpu_ids=step.gpu_ids,
            )

            if status.status not in ("healthy", "starting"):
                logger.error(f"Failed to start {step.endpoint_name}: {status.status}")
                return False

            completed_steps.add(step.step_id)

        return True

    async def _start_scheduled_endpoint(
        self,
        endpoint_name: str,
        gpu_ids: list[int],
    ) -> EndpointStatus:
        """Start an endpoint with pre-computed GPU assignment.

        Args:
            endpoint_name: Name of the endpoint (e.g., "cap_REASONING")
            gpu_ids: GPUs to use (from scheduler)

        Returns:
            EndpointStatus
        """
        from gaius.models.registry import get_model_registry, TaskType

        # Parse capability from endpoint name
        if endpoint_name.startswith("cap_"):
            capability_key = endpoint_name[4:]  # Remove "cap_" prefix
            try:
                task_type = TaskType(capability_key)
            except ValueError:
                return EndpointStatus(
                    agent_alias=endpoint_name,
                    model="",
                    port=None,
                    gpu_ids=gpu_ids,
                    status="invalid_capability",
                    startup_message=f"Unknown capability: {capability_key}",
                )

            # Get the model for this capability
            registry = get_model_registry()
            model_spec = registry.get_for_task(task_type, require_local=True)

            if not model_spec:
                return EndpointStatus(
                    agent_alias=endpoint_name,
                    model="",
                    port=None,
                    gpu_ids=gpu_ids,
                    status="no_model",
                    startup_message=f"No model for capability: {capability_key}",
                )

            return await self._start_capability_endpoint(
                endpoint_name=endpoint_name,
                model_spec=model_spec,
                task_type=task_type,
                gpus=gpu_ids,
            )
        else:
            # Regular endpoint from config
            return await self.start_endpoint(endpoint_name)

    async def _find_and_evict_for_resources(
        self,
        required_gpus: int,
        required_memory_mb: int,
        requesting_priority: int,
    ) -> bool:
        """Find and evict idle endpoints to free resources.

        Yunikorn-style preemption rules:
        1. Only evict if requester priority >= endpoint priority
        2. Prefer idle endpoints over active ones
        3. Prefer lower priority endpoints
        4. Never evict endpoints with in-flight requests

        Args:
            required_gpus: Number of GPUs needed
            required_memory_mb: GPU memory needed
            requesting_priority: Priority of requesting workload

        Returns:
            True if enough resources freed, False otherwise
        """
        candidates = []

        # First check capability-registered endpoints (tracked with activity)
        for name, activity in self._endpoint_activity.items():
            # Skip endpoints with in-flight requests
            if activity.requests_in_flight > 0:
                continue

            # Skip higher priority endpoints
            if activity.priority > requesting_priority:
                continue

            status = self.get_endpoint_status(name)
            if status:
                candidates.append((name, activity, status))

        # Also check vLLM processes not tracked in _endpoint_activity
        # These are legacy endpoints started by the engine on initialization
        for proc_name, proc in self._vllm._processes.items():
            if proc_name in self._endpoint_activity:
                continue  # Already tracked

            # Create a synthetic activity for legacy endpoints
            # Assume they are NORMAL priority and potentially idle
            synthetic_activity = EndpointActivity(
                endpoint_name=proc_name,
                capability="REASONING",  # Assume vLLM endpoints are for reasoning
                model_id=proc.model,
                priority=2,  # NORMAL priority
            )

            # Legacy endpoints are considered idle if we have no tracking info
            # This makes them prime candidates for eviction when needed

            status = self.get_endpoint_status(proc_name)
            if status and status.status == "healthy":
                candidates.append((proc_name, synthetic_activity, status))

        # Sort: idle first, then by priority (lowest first), then by idle time (longest first)
        candidates.sort(
            key=lambda x: (
                not x[1].is_idle,  # Idle first
                x[1].priority,  # Lower priority first
                -x[1].idle_seconds,  # Longer idle first
            )
        )

        freed_gpus = 0
        to_evict = []

        for name, activity, status in candidates:
            to_evict.append(name)
            freed_gpus += len(status.gpu_ids)

            if freed_gpus >= required_gpus:
                break

        if freed_gpus < required_gpus:
            logger.warning(
                f"Cannot free {required_gpus} GPUs: only {freed_gpus} available from "
                f"{len(candidates)} candidates"
            )
            return False

        # Execute evictions
        for name in to_evict:
            logger.info(f"Evicting endpoint {name} to free resources for higher-priority workload")
            await self.stop_endpoint(name)
            self._unregister_capability(name)

        # Wait for GPU memory to be freed
        await asyncio.sleep(2)
        return True

    def record_request_start(self, endpoint_name: str) -> None:
        """Record that a request started on an endpoint.

        Args:
            endpoint_name: Name of the endpoint
        """
        if endpoint_name in self._endpoint_activity:
            self._endpoint_activity[endpoint_name].requests_in_flight += 1
            self._endpoint_activity[endpoint_name].last_request_time = time.time()

    def record_request_end(self, endpoint_name: str) -> None:
        """Record that a request completed on an endpoint.

        Args:
            endpoint_name: Name of the endpoint
        """
        if endpoint_name in self._endpoint_activity:
            activity = self._endpoint_activity[endpoint_name]
            activity.requests_in_flight = max(0, activity.requests_in_flight - 1)
            activity.last_request_time = time.time()

    # ─────────────────────────────────────────────────────────────────────────
    # GPU Memory-Based Eviction for Transient Workloads
    # ─────────────────────────────────────────────────────────────────────────

    async def _evict_for_gpu_memory(
        self,
        workload_id: str,
        required_memory_mb: int,
        metadata: dict | None = None,
        allow_baseline_eviction: bool = False,
    ) -> tuple[list[str], list[str]]:
        """Evict vLLM endpoints to free GPU memory for transient CUDA workloads.

        Used by flows like Docling that need raw GPU VRAM (not vLLM endpoints).
        This identifies endpoints using the target GPUs and evicts them.

        Args:
            workload_id: ID of the requesting workload (for logging)
            required_memory_mb: GPU memory required in MB
            metadata: Workload metadata (may contain 'target_gpus' hint)
            allow_baseline_eviction: If True, allows evicting baseline endpoints.
                Used by VectorSearch/ColNomic workloads for dynamic scheduling
                where user-requested operations take priority.

        Returns:
            Tuple of (evicted_endpoints, restore_plan)
        """
        evicted: list[str] = []
        restore_plan: list[str] = []

        # Determine target GPUs from metadata or flow scheduler config
        # Default: GPUs 0-3 are for vLLM, flows use 4-5
        # But if flow needs more memory, we may need to evict from 0-3
        target_gpus: set[int] = set()

        if metadata and "target_gpus" in metadata:
            target_gpus = set(metadata["target_gpus"])
        else:
            # Check GPU memory availability across all GPUs
            # For now, assume the flow will use GPUs specified in CUDA_VISIBLE_DEVICES
            # We need to evict endpoints on those GPUs
            from ..resources.gpu_monitor import get_gpu_memory_free

            try:
                gpu_free = await get_gpu_memory_free()
            except Exception as e:
                logger.warning(f"Could not query GPU memory: {e}")
                gpu_free = {}

            # Find GPUs with insufficient free memory
            required_gb = required_memory_mb / 1024
            for gpu_id, free_gb in gpu_free.items():
                if free_gb < required_gb:
                    target_gpus.add(gpu_id)

        if not target_gpus:
            logger.debug(f"No GPU eviction needed for workload {workload_id}")
            return evicted, restore_plan

        logger.info(
            f"Workload {workload_id} needs {required_memory_mb}MB, "
            f"checking GPUs: {sorted(target_gpus)}"
        )

        # Get baseline endpoints - normally protected but can be evicted
        # when allow_baseline_eviction=True (for VectorSearch/ColNomic workloads)
        baseline_endpoints = set(
            getattr(self.config.startup, "preload_endpoints", [])
        )

        # Find endpoints using the target GPUs
        for proc_name, proc in self._vllm._processes.items():
            proc_gpus = set(proc.gpu_ids) if proc.gpu_ids else set()
            if proc_gpus & target_gpus:
                # This endpoint uses one of our target GPUs
                if proc_name in baseline_endpoints and not allow_baseline_eviction:
                    # Protect baseline endpoints for flow workloads (Docling, etc.)
                    # But allow eviction for user-interactive workloads (VectorSearch)
                    logger.warning(
                        f"Refusing to evict baseline endpoint {proc_name} (GPUs {proc.gpu_ids}) "
                        f"for workload {workload_id}. Flow should use non-overlapping GPUs. "
                        f"Guru: #ORCH.00000010.BASELINEPROTECT"
                    )
                    continue

                logger.info(
                    f"Endpoint {proc_name} uses GPUs {proc.gpu_ids}, "
                    f"overlaps with target {target_gpus}"
                )
                evicted.append(proc_name)
                restore_plan.append(proc_name)

        if not evicted:
            logger.debug(f"No endpoints to evict for workload {workload_id}")
            return evicted, restore_plan

        # Execute evictions
        for name in evicted:
            try:
                logger.info(f"Evicting endpoint {name} for transient workload {workload_id}")
                await self.stop_endpoint(name)
                self._unregister_capability(name)
            except Exception as e:
                logger.error(f"Failed to evict endpoint {name}: {e}")

        # Wait for GPU memory to be freed (vLLM unload takes a moment)
        if evicted:
            logger.info(f"Waiting for GPU memory to be freed after evicting {evicted}")
            await asyncio.sleep(5)

        return evicted, restore_plan

    # ─────────────────────────────────────────────────────────────────────────
    # Workload Management (Yunikorn-Style Makespan)
    # ─────────────────────────────────────────────────────────────────────────

    async def begin_workload(
        self,
        request: "WorkloadRequest",
    ) -> "WorkloadResult":
        """Allocate resources for a workload, evicting if needed.

        Yunikorn-style makespan management: the workload declares what
        capabilities it needs and for how long. The orchestrator allocates
        resources, evicting idle endpoints if necessary.

        For GPU memory-based workloads (like Docling flows), this will:
        1. Check available GPU memory on target GPUs
        2. Evict endpoints using those GPUs if memory insufficient
        3. Track evicted endpoints for restoration after workload completes

        Args:
            request: WorkloadRequest with capabilities and resource requirements

        Returns:
            WorkloadResult with allocated endpoints and eviction info
        """
        from ..workloads import (
            WorkloadRequest,
            WorkloadResult,
            EndpointAllocation,
            ActiveWorkload,
        )

        start_time = time.time()
        allocated: dict = {}
        evicted: list[str] = []
        restore_plan: list[str] = []
        schedule_result = None  # Will hold OR-Tools result if capability-based

        logger.info(
            f"Beginning workload {request.workload_id} "
            f"(type={request.workload_type.name}, priority={request.priority.name})"
        )

        # Handle GPU memory-based workloads (e.g., Docling flows, VectorSearch)
        # These need raw GPU VRAM, not vLLM endpoints
        if request.is_gpu_workload and not request.required_capabilities:
            # VectorSearch workloads set allow_baseline_eviction=True in metadata
            # to enable Yunikorn-style dynamic scheduling
            allow_baseline = request.metadata.get("allow_baseline_eviction", False)
            evicted, restore_plan = await self._evict_for_gpu_memory(
                workload_id=request.workload_id,
                required_memory_mb=request.estimated_memory_mb,
                metadata=request.metadata,
                allow_baseline_eviction=allow_baseline,
            )

        # Use OR-Tools scheduler for capability-based workloads
        if request.required_capabilities:
            from ..scheduling import MakespanScheduler, ORTOOLS_AVAILABLE

            if not ORTOOLS_AVAILABLE:
                return WorkloadResult(
                    success=False,
                    workload_id=request.workload_id,
                    error="OR-Tools not available.\n"
                          "  Install: uv sync --extra scheduler\n"
                          "  Guru Meditation: #SCH.00000001.NOORDEPS",
                    wait_time_ms=int((time.time() - start_time) * 1000),
                )

            # Build current and target scheduling tasks
            current_tasks = self._build_current_scheduling_tasks()
            target_tasks = self._build_target_scheduling_tasks(request, current_tasks)

            logger.info(
                f"Scheduling transition: current={[t.endpoint_name for t in current_tasks]}, "
                f"target={[t.endpoint_name for t in target_tasks]}"
            )

            # Plan the transition with OR-Tools
            scheduler = MakespanScheduler(
                total_gpus=self.resource_manager.total_gpus,
                reserved_gpus=set(self.resource_manager.reserved_gpus),
            )

            schedule_result = scheduler.plan_transition(current_tasks, target_tasks)

            if not schedule_result.success:
                logger.error(f"Scheduling failed: {schedule_result.error}")
                return WorkloadResult(
                    success=False,
                    workload_id=request.workload_id,
                    error=schedule_result.error,
                    wait_time_ms=int((time.time() - start_time) * 1000),
                )

            # plan is guaranteed to exist when success=True
            plan = schedule_result.plan
            assert plan is not None, "plan should exist when success=True"

            logger.info(
                f"Schedule found: makespan={plan.total_makespan_ms}ms, "
                f"evicting={plan.evicted_endpoints}, "
                f"assignments={plan.gpu_assignments}"
            )

            # Execute the transition plan
            success = await self._execute_transition_plan(plan)

            if not success:
                return WorkloadResult(
                    success=False,
                    workload_id=request.workload_id,
                    error="Transition plan execution failed.\n"
                          "  Guru Meditation: #SCH.00000003.EXECFAIL",
                    wait_time_ms=int((time.time() - start_time) * 1000),
                )

            # Build allocated endpoints from the plan
            evicted = plan.evicted_endpoints
            restore_plan = plan.restore_plan

            for task_type in request.required_capabilities:
                capability_key = task_type.value
                endpoint_name = f"cap_{capability_key}"

                if endpoint_name in plan.gpu_assignments:
                    status = self.get_endpoint_status(endpoint_name)
                    if status:
                        allocated[task_type] = EndpointAllocation(
                            endpoint_name=endpoint_name,
                            capability=task_type,
                            port=status.port or 0,
                            healthy=status.status == "healthy",
                            model_id=status.model,
                        )

        # Track this workload
        request.started_at = datetime.now()
        result = WorkloadResult(
            success=True,
            workload_id=request.workload_id,
            allocated_endpoints=allocated,
            evicted_endpoints=evicted,
            restore_plan=restore_plan,
            wait_time_ms=int((time.time() - start_time) * 1000),
        )

        self._active_workloads[request.workload_id] = ActiveWorkload(
            request=request,
            result=result,
        )

        # Create agenda incident for tracking makespan and control mode
        if self._agenda_tracker:
            try:
                await self._agenda_tracker.on_workload_begin(
                    request=request,
                    schedule_result=schedule_result,
                )
            except Exception as e:
                logger.warning(f"Failed to create agenda incident: {e}")

        logger.info(
            f"Workload {request.workload_id} started with "
            f"{len(allocated)} endpoints allocated"
        )

        return result

    async def complete_workload(self, workload_id: str) -> None:
        """Mark workload complete and restore evicted endpoints.

        Called when a workload finishes to release resources and
        potentially restore previously evicted endpoints.

        The sequence is:
        1. Stop transient endpoints allocated for this workload (e.g., cap_reasoning)
        2. Wait for GPU memory release
        3. Restore previously evicted baseline endpoints

        Args:
            workload_id: ID of the completed workload
        """
        if workload_id not in self._active_workloads:
            logger.warning(f"Unknown workload {workload_id}")
            return

        workload = self._active_workloads.pop(workload_id)
        workload.request.completed_at = datetime.now()

        logger.info(
            f"Completing workload {workload_id} "
            f"(duration={workload.elapsed_s:.1f}s)"
        )

        # Step 1: Stop transient endpoints allocated for this workload
        # These are dynamically created endpoints like cap_reasoning
        allocated_endpoints = [
            alloc.endpoint_name
            for alloc in workload.result.allocated_endpoints.values()
        ]

        if allocated_endpoints:
            logger.info(f"Stopping transient endpoints: {allocated_endpoints}")
            stop_tasks = [
                self.stop_endpoint(endpoint_name)
                for endpoint_name in allocated_endpoints
            ]
            results = await asyncio.gather(*stop_tasks, return_exceptions=True)
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    logger.error(
                        f"Failed to stop transient endpoint {allocated_endpoints[i]}: {result}"
                    )

            # Wait for GPU memory to be released
            await asyncio.sleep(3)

        # Step 2: Restore evicted endpoints if specified
        restore_success = True
        restore_error = None
        for endpoint_name in workload.result.restore_plan:
            try:
                logger.info(f"Restoring evicted endpoint: {endpoint_name}")
                await self.start_endpoint(endpoint_name)
            except Exception as e:
                restore_success = False
                restore_error = str(e)
                logger.error(f"Failed to restore endpoint {endpoint_name}: {e}")

        # Complete agenda incident tracking
        if self._agenda_tracker:
            try:
                from ..workloads import WorkloadResult

                # Create completion result for agenda tracker
                completion_result = WorkloadResult(
                    success=restore_success,
                    workload_id=workload_id,
                    error=restore_error,
                    wait_time_ms=int(workload.elapsed_s * 1000),
                )
                await self._agenda_tracker.on_workload_complete(
                    workload_id=workload_id,
                    result=completion_result,
                )
            except Exception as e:
                logger.warning(f"Failed to complete agenda incident: {e}")

    def get_active_workloads(self) -> dict[str, dict]:
        """Get information about active workloads.

        Returns:
            Dict mapping workload_id to workload info
        """
        result = {}
        for wid, workload in self._active_workloads.items():
            result[wid] = {
                "workload_id": wid,
                "type": workload.request.workload_type.name,
                "priority": workload.request.priority.name,
                "capabilities": [c.value for c in workload.request.required_capabilities],
                "elapsed_s": workload.elapsed_s,
                "estimated_duration_s": workload.request.estimated_duration_s,
                "is_overdue": workload.is_overdue,
                "endpoints": [
                    alloc.endpoint_name
                    for alloc in workload.result.allocated_endpoints.values()
                ],
                "restore_plan": workload.result.restore_plan,
            }
        return result

    # ─────────────────────────────────────────────────────────────────────────
    # Clean Start (BDD: '/evolve start' scenario)
    # ─────────────────────────────────────────────────────────────────────────

    async def clean_start(
        self, endpoints: Optional[list[str]] = None
    ) -> dict[str, Any]:
        """Clean start: kill stale processes and start fresh.

        This is the recommended way to start Gaius for overnight evolution runs.

        BDD: "Start evolution daemon with '/evolve start'"
        - Orphaned vLLM processes should be cleaned up
        - The specified endpoint should start on designated GPU

        Args:
            endpoints: Endpoints to start (default: ["reasoning"])

        Returns:
            Dict with cleanup and startup results
        """
        logger.info("Performing clean start...")

        # Step 1: Cleanup stale processes
        cleanup_result = await self.cleanup_stale_processes()

        # Step 2: Start requested endpoints
        if endpoints is None:
            endpoints = ["reasoning"]  # Default for evolution

        startup_results: dict[str, dict[str, Any]] = {}
        for alias in endpoints:
            if alias in self.config.agents:
                try:
                    status = await self.start_endpoint(alias)
                    startup_results[alias] = {
                        "success": status.status == "healthy",
                        "port": status.port,
                        "gpu_ids": status.gpu_ids,
                    }
                except Exception as e:
                    logger.error(f"Failed to start {alias}: {e}")
                    startup_results[alias] = {
                        "success": False,
                        "error": str(e),
                    }

        # Determine overall success
        success = any(r.get("success", False) for r in startup_results.values())

        return {
            "cleanup": cleanup_result,
            "startup": startup_results,
            "success": success,
        }

    async def cleanup_stale_processes(self) -> CleanupResult:
        """Kill stale vLLM processes to free GPU memory.

        BDD: "Orphaned vLLM processes should be cleaned up"

        Uses two detection methods:
        1. pgrep for vLLM/python processes with GPU-related args
        2. nvidia-smi to find ANY process using significant GPU memory

        Returns:
            CleanupResult with details
        """
        result = CleanupResult()

        try:
            # Get tracked PIDs from the vLLM controller
            tracked_pids = {
                p.pid
                for p in self._vllm._processes.values()
                if p.process is not None and p.pid is not None
            }

            # Also track our own PID and parent PIDs
            my_pid = os.getpid()
            tracked_pids.add(my_pid)
            try:
                ppid = os.getppid()
                tracked_pids.add(ppid)
            except Exception:
                pass

            # Method 1: Find vLLM processes via pgrep
            ps_result = subprocess.run(
                ["pgrep", "-f", "vllm|VLLM"],
                capture_output=True,
                text=True,
            )

            vllm_pids = set()
            if ps_result.returncode == 0 and ps_result.stdout.strip():
                for pid_str in ps_result.stdout.strip().split("\n"):
                    try:
                        vllm_pids.add(int(pid_str.strip()))
                    except ValueError:
                        continue

            # Method 2: Find GPU-hogging processes via nvidia-smi
            # This catches zombies that pgrep might miss
            gpu_pids = set()
            try:
                nvidia_result = subprocess.run(
                    ["nvidia-smi", "--query-compute-apps=pid,used_memory", "--format=csv,noheader,nounits"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                if nvidia_result.returncode == 0 and nvidia_result.stdout.strip():
                    for line in nvidia_result.stdout.strip().split("\n"):
                        parts = line.strip().split(", ")
                        if len(parts) >= 2:
                            try:
                                pid = int(parts[0])
                                mem_mb = int(parts[1])
                                # Only target processes using >100MB GPU memory
                                if mem_mb > 100:
                                    gpu_pids.add(pid)
                            except ValueError:
                                continue
            except (subprocess.TimeoutExpired, FileNotFoundError):
                logger.debug("nvidia-smi not available for GPU process detection")

            # Combine both detection methods
            candidate_pids = vllm_pids | gpu_pids
            result.processes_found = len(candidate_pids)

            # Kill untracked processes
            for pid in candidate_pids:
                if pid in tracked_pids:
                    continue

                try:
                    # Double-check it's a GPU/vLLM process before killing
                    # Read /proc/pid/cmdline to verify
                    try:
                        with open(f"/proc/{pid}/cmdline", "r") as f:
                            cmdline = f.read()
                            # Only kill if it looks like a GPU workload
                            if not any(pattern in cmdline.lower() for pattern in
                                       ["vllm", "torch", "cuda", "python", "gpu"]):
                                logger.debug(f"Skipping PID {pid} - doesn't look like GPU workload")
                                continue
                    except (FileNotFoundError, PermissionError):
                        # Process may have died or we can't read - skip
                        continue

                    os.kill(pid, 9)  # SIGKILL
                    result.processes_killed += 1
                    result.pids_killed.append(pid)
                    logger.info(f"Killed stale GPU process: {pid}")
                except ProcessLookupError:
                    pass  # Already dead
                except PermissionError:
                    result.errors.append(f"Permission denied for PID {pid}")

            # Clear CUDA cache if available
            try:
                import torch

                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
                    result.cuda_cache_cleared = True
                    logger.info("Cleared CUDA cache")
            except ImportError:
                pass

            # Brief wait for GPU memory to be freed
            await asyncio.sleep(2)

            logger.info(
                f"Cleanup complete: found {result.processes_found}, "
                f"killed {result.processes_killed}"
            )

        except Exception as e:
            result.errors.append(str(e))
            logger.error(f"Cleanup error: {e}")

        return result

    # ─────────────────────────────────────────────────────────────────────────
    # State Reconciliation (Self-Healing)
    # ─────────────────────────────────────────────────────────────────────────

    async def discover_actual_state(self) -> dict[int, dict]:
        """Discover what's actually running on inference ports.

        Scans ports 8080-8095 and queries /v1/models to find actual model IDs.
        Also checks GPU VRAM usage via nvidia-smi.

        Returns:
            Dict mapping port -> {"model": str, "pid": int, "gpu": int}
        """
        import httpx

        actual = {}

        # Scan inference ports
        async with httpx.AsyncClient(timeout=2.0) as client:
            for port in range(8080, 8096):
                try:
                    resp = await client.get(f"http://localhost:{port}/v1/models")
                    if resp.status_code == 200:
                        data = resp.json()
                        models = data.get("data", [])
                        if models:
                            model_id = models[0].get("id", "unknown")
                            actual[port] = {"model": model_id, "port": port}
                except Exception:
                    pass  # Port not responding

        # Enrich with process info
        try:
            ps_result = subprocess.run(
                ["pgrep", "-af", "vllm serve"],
                capture_output=True,
                text=True,
            )
            if ps_result.returncode == 0:
                for line in ps_result.stdout.strip().split("\n"):
                    if not line.strip():
                        continue
                    parts = line.split(None, 1)
                    if len(parts) >= 2:
                        try:
                            pid = int(parts[0])
                        except ValueError:
                            continue  # Skip if PID isn't numeric
                        cmd = parts[1]
                        # Extract port from command (look for --port followed by number)
                        import re
                        port_match = re.search(r"--port\s+(\d+)", cmd)
                        if port_match:
                            port = int(port_match.group(1))
                            if port in actual:
                                actual[port]["pid"] = pid
                            else:
                                # Process starting but not yet responding
                                actual[port] = {
                                    "model": "unknown (starting?)",
                                    "port": port,
                                    "pid": pid,
                                }
        except Exception as e:
            logger.debug(f"Process discovery failed: {e}")

        return actual

    async def reconcile_state(self) -> dict[str, Any]:
        """Compare desired state vs actual and fix mismatches.

        This is the core self-healing logic. It:
        1. Discovers what's actually running
        2. Compares to desired state from config
        3. Kills processes on wrong ports or with wrong models
        4. Starts missing endpoints

        Returns:
            Dict with reconciliation results
        """
        # Explicitly typed to help type checker with heterogeneous dict
        actions: list[dict[str, Any]] = []
        errors: list[str] = []
        results: dict[str, Any] = {
            "actual_state": {},
            "desired_state": {},
            "actions": actions,
            "errors": errors,
        }

        # Build desired state from config
        desired: dict[int, dict] = {}
        for name, agent in self.config.agents.items():
            if agent.endpoint:
                desired[agent.endpoint.port] = {
                    "name": name,
                    "model": agent.model,
                    "port": agent.endpoint.port,
                }

        results["desired_state"] = desired

        # Discover actual state
        actual = await self.discover_actual_state()
        results["actual_state"] = actual

        # Find orphans (running on ports we don't expect)
        for port, info in actual.items():
            if port not in desired:
                # Orphan process - kill it
                if info.get("pid"):
                    try:
                        os.kill(info["pid"], 9)
                        actions.append({
                            "action": "killed_orphan",
                            "port": port,
                            "pid": info["pid"],
                            "model": info.get("model"),
                        })
                        logger.warning(f"Killed orphan vLLM on port {port}: {info.get('model')}")
                    except Exception as e:
                        errors.append(f"Failed to kill orphan on {port}: {e}")

        # Find mismatches (wrong model on expected port)
        for port, desired_info in desired.items():
            actual_info = actual.get(port)
            if actual_info:
                # Check if model matches
                actual_model = actual_info.get("model", "")
                desired_model = desired_info.get("model", "")

                # Model IDs may have different formats, compare base names
                actual_base = actual_model.split("/")[-1].lower()
                desired_base = desired_model.split("/")[-1].lower()

                if actual_base != desired_base:
                    # Wrong model - kill and restart
                    if actual_info.get("pid"):
                        try:
                            os.kill(actual_info["pid"], 9)
                            actions.append({
                                "action": "killed_mismatch",
                                "port": port,
                                "pid": actual_info["pid"],
                                "expected_model": desired_model,
                                "actual_model": actual_model,
                            })
                            logger.warning(
                                f"Killed mismatched model on port {port}: "
                                f"expected {desired_model}, got {actual_model}"
                            )
                            # Wait for GPU memory to free
                            await asyncio.sleep(3)
                            # Restart correct endpoint
                            await self.start_endpoint(desired_info["name"])
                            actions.append({
                                "action": "restarted",
                                "port": port,
                                "endpoint": desired_info["name"],
                            })
                        except Exception as e:
                            errors.append(f"Failed to fix mismatch on {port}: {e}")

        logger.info(
            f"Reconciliation complete: {len(results['actions'])} actions, "
            f"{len(results['errors'])} errors"
        )

        return results

    # ─────────────────────────────────────────────────────────────────────────
    # GPU Health Monitoring (BDD: GPU idle state monitoring)
    # ─────────────────────────────────────────────────────────────────────────

    async def _health_loop(self) -> None:
        """Background health monitoring loop."""
        while self._running:
            try:
                await self._update_gpu_health()
                await self._check_endpoint_health()
            except Exception as e:
                logger.error(f"Health check error: {e}")

            await asyncio.sleep(self._health_interval)

    async def _update_gpu_health(self) -> None:
        """Update GPU utilization metrics."""
        try:
            import pynvml

            pynvml.nvmlInit()

            device_count = pynvml.nvmlDeviceGetCount()
            for i in range(device_count):
                handle = pynvml.nvmlDeviceGetHandleByIndex(i)
                util = pynvml.nvmlDeviceGetUtilizationRates(handle)
                self._gpu_utilization[i] = util.gpu / 100.0

                # Update resource manager
                memory = pynvml.nvmlDeviceGetMemoryInfo(handle)
                temp = pynvml.nvmlDeviceGetTemperature(
                    handle, pynvml.NVML_TEMPERATURE_GPU
                )
                self.resource_manager.update_gpu_status(
                    i,
                    vram_used_gb=memory.used / (1024**3),
                    temperature_c=temp,
                    utilization_pct=util.gpu,
                )

            pynvml.nvmlShutdown()
            self._last_health_check = datetime.now()

        except ImportError:
            # pynvml not available, skip GPU metrics
            pass
        except Exception as e:
            logger.debug(f"GPU health update failed: {e}")

    async def _check_endpoint_health(self) -> None:
        """Check health of all running endpoints with stuck state detection.

        AIOps autonomous health loop:
        - Detect endpoints stuck in STARTING for >5 minutes
        - Detect endpoints stuck in STOPPING for >2 minutes
        - Auto-remediate low-severity issues (restart)
        - Record events for audit trail
        """
        now = time.time()

        for alias, proc in list(self._vllm._processes.items()):
            # Handle STARTING state - check if endpoint has become healthy
            if proc.status == ProcessStatus.STARTING:
                # Try HTTP health check to see if startup is complete
                healthy = await self._vllm._check_health(proc)
                if healthy:
                    proc.status = ProcessStatus.HEALTHY
                    proc.consecutive_failures = 0
                    logger.info(f"Endpoint {alias} transitioned STARTING → HEALTHY")
                    continue

                # Not healthy yet - check for stuck starting timeout
                if proc.started_at:
                    elapsed = now - proc.started_at.timestamp()
                    if elapsed > self._stuck_starting_timeout:
                        await self._remediate_stuck_starting(alias, proc, elapsed)
                continue

            # Handle stuck STOPPING state
            if proc.status == ProcessStatus.STOPPING:
                # Use last_health_check as proxy for when stop was initiated
                if proc.last_health_check:
                    elapsed = now - proc.last_health_check.timestamp()
                    if elapsed > self._stuck_stopping_timeout:
                        await self._remediate_stuck_stopping(alias, proc, elapsed)
                continue

            # Skip STOPPED - nothing to check
            if proc.status == ProcessStatus.STOPPED:
                continue

            # Check if process is still running (HEALTHY, UNHEALTHY, FAILED)
            if proc.process and proc.process.returncode is not None:
                logger.warning(
                    f"Process for {alias} exited with code {proc.process.returncode}"
                )
                proc.status = ProcessStatus.FAILED
                # Attempt auto-restart if enabled
                await self._maybe_restart_endpoint(alias)
                continue

            # HTTP health check
            healthy = await self._vllm._check_health(proc)
            if healthy:
                proc.status = ProcessStatus.HEALTHY
                proc.consecutive_failures = 0
                # Reset restart attempts on successful health check
                self._restart_attempts[alias] = 0
            else:
                proc.consecutive_failures += 1
                if proc.consecutive_failures >= 3:
                    proc.status = ProcessStatus.UNHEALTHY
                    # Attempt auto-restart if enabled
                    await self._maybe_restart_endpoint(alias)

    async def _maybe_restart_endpoint(self, alias: str) -> None:
        """Attempt to restart a failed endpoint if auto-restart is enabled.

        Args:
            alias: Endpoint alias to restart
        """
        if not self._auto_restart_enabled:
            return

        # Check restart attempts
        attempts = self._restart_attempts.get(alias, 0)
        if attempts >= self._max_restart_attempts:
            logger.warning(
                f"Endpoint {alias} exceeded max restart attempts ({self._max_restart_attempts}), "
                "giving up. Manual intervention required."
            )
            return

        # Increment attempts before trying
        self._restart_attempts[alias] = attempts + 1

        logger.info(
            f"Auto-restarting endpoint {alias} (attempt {attempts + 1}/{self._max_restart_attempts})"
        )

        try:
            # Brief cooldown before restart
            await asyncio.sleep(5)

            # Restart the endpoint
            status = await self.restart_endpoint(alias)

            if status.status == "healthy":
                logger.info(f"Successfully restarted endpoint {alias}")
                self._restart_attempts[alias] = 0  # Reset on success
            else:
                logger.warning(
                    f"Restart of {alias} returned status: {status.status}"
                )

        except Exception as e:
            logger.error(f"Failed to restart endpoint {alias}: {e}")

    async def _remediate_stuck_starting(
        self, alias: str, proc: "VLLMProcess", elapsed: float
    ) -> None:
        """Auto-remediate endpoint stuck in STARTING state.

        AIOps: Low severity - auto-remediation without approval.

        Args:
            alias: Endpoint alias
            proc: VLLMProcess instance
            elapsed: Seconds spent in STARTING state
        """
        logger.warning(
            f"Endpoint {alias} stuck in STARTING for {elapsed:.0f}s (threshold: "
            f"{self._stuck_starting_timeout}s). Auto-remediating..."
        )

        # Record AIOps event
        await self._record_aiops_event(
            category="stuck_state",
            severity="medium",
            endpoint=alias,
            description=f"Endpoint stuck in STARTING state for {elapsed:.0f} seconds",
            context={
                "elapsed_seconds": elapsed,
                "threshold_seconds": self._stuck_starting_timeout,
                "pid": proc.pid,
                "model": proc.model,
            },
            remediation_action="force_restart",
            status="auto_remediated",
        )

        # Kill the stuck process
        if proc.pid:
            try:
                import signal
                os.kill(proc.pid, signal.SIGKILL)
                logger.info(f"Killed stuck process {proc.pid} for {alias}")
            except ProcessLookupError:
                logger.debug(f"Process {proc.pid} already gone")
            except Exception as e:
                logger.error(f"Failed to kill process {proc.pid}: {e}")

        # Mark as failed and clear
        proc.status = ProcessStatus.FAILED
        proc.process = None
        proc.pid = None

        # Schedule restart after cleanup delay
        await asyncio.sleep(5)
        await self._maybe_restart_endpoint(alias)

    async def _remediate_stuck_stopping(
        self, alias: str, proc: "VLLMProcess", elapsed: float
    ) -> None:
        """Auto-remediate endpoint stuck in STOPPING state.

        AIOps: Low severity - auto-remediation without approval.

        Args:
            alias: Endpoint alias
            proc: VLLMProcess instance
            elapsed: Seconds spent in STOPPING state
        """
        logger.warning(
            f"Endpoint {alias} stuck in STOPPING for {elapsed:.0f}s (threshold: "
            f"{self._stuck_stopping_timeout}s). Force killing..."
        )

        # Record AIOps event
        await self._record_aiops_event(
            category="stuck_state",
            severity="low",
            endpoint=alias,
            description=f"Endpoint stuck in STOPPING state for {elapsed:.0f} seconds",
            context={
                "elapsed_seconds": elapsed,
                "threshold_seconds": self._stuck_stopping_timeout,
                "pid": proc.pid,
            },
            remediation_action="force_kill",
            status="auto_remediated",
        )

        # Force kill the stuck process
        if proc.pid:
            try:
                import signal
                os.kill(proc.pid, signal.SIGKILL)
                logger.info(f"Force killed stuck stopping process {proc.pid}")
            except ProcessLookupError:
                logger.debug(f"Process {proc.pid} already gone")
            except Exception as e:
                logger.error(f"Failed to force kill process {proc.pid}: {e}")

        # Mark as stopped
        proc.status = ProcessStatus.STOPPED
        proc.process = None
        proc.pid = None

    async def _record_aiops_event(
        self,
        category: str,
        severity: str,
        endpoint: str | None,
        description: str,
        context: dict | None = None,
        remediation_action: str | None = None,
        status: str = "detected",
    ) -> int | None:
        """Record an AIOps event to the database.

        Args:
            category: Event category (stuck_state, gpu_error, endpoint_failure)
            severity: low, medium, high, critical
            endpoint: Affected endpoint name
            description: Human-readable description
            context: Additional context as JSON
            remediation_action: Action taken/proposed
            status: Event status

        Returns:
            Event ID if recorded, None on error
        """
        try:
            import asyncpg

            from gaius.core.config import get_database_url

            db_url = get_database_url()
            conn = await asyncpg.connect(db_url)

            try:
                import json
                event_id = await conn.fetchval(
                    """
                    INSERT INTO aiops_events
                        (category, severity, status, endpoint, description, context,
                         remediation_action, approved_by, approved_at, resolved_at)
                    VALUES ($1, $2::aiops_severity, $3::aiops_status, $4, $5, $6::jsonb,
                            $7, $8, $9, $10)
                    RETURNING id
                    """,
                    category,
                    severity,
                    status,
                    endpoint,
                    description,
                    json.dumps(context or {}),
                    remediation_action,
                    "system" if status == "auto_remediated" else None,
                    datetime.now() if status == "auto_remediated" else None,
                    datetime.now() if status in ("auto_remediated", "resolved") else None,
                )
                logger.info(
                    f"Recorded AIOps event {event_id}: {category} ({severity}) - {description}"
                )
                return event_id
            finally:
                await conn.close()

        except ImportError:
            logger.debug("asyncpg not available, skipping AIOps event recording")
        except Exception as e:
            logger.error(f"Failed to record AIOps event: {e}")

        return None

    def get_gpu_utilization(self) -> dict[int, float]:
        """Get current GPU utilization.

        BDD: "Evolution daemon monitors GPU idle state"
        - GPU utilization drops below 20% → trigger evolution

        Returns:
            Dict mapping GPU ID to utilization (0-1)
        """
        return self._gpu_utilization.copy()

    def is_gpu_idle(self, threshold: float = 0.2) -> bool:
        """Check if GPUs are idle (for evolution triggering).

        Args:
            threshold: Utilization threshold (default 20%)

        Returns:
            True if average utilization below threshold
        """
        if not self._gpu_utilization:
            return True  # No data, assume idle

        avg_util = sum(self._gpu_utilization.values()) / len(self._gpu_utilization)
        return avg_util < threshold

    def get_idle_gpus(self, threshold: float = 0.2) -> list[int]:
        """Get list of idle GPU IDs.

        Args:
            threshold: Utilization threshold (default 20%)

        Returns:
            List of GPU IDs below threshold
        """
        return [
            gpu_id
            for gpu_id, util in self._gpu_utilization.items()
            if util < threshold
        ]

    # ─────────────────────────────────────────────────────────────────────────
    # GPU Reclamation (for large model deployment)
    # ─────────────────────────────────────────────────────────────────────────

    async def prepare_for_large_model(self, target_gpus: list[int]) -> dict[str, Any]:
        """Scale down optillm workers to free resources for large model.

        When deploying a large reasoning model (e.g., QwQ-32B across 4 GPUs),
        we reduce optillm workers to minimize resource contention.

        Args:
            target_gpus: GPU IDs that will be used for the large model

        Returns:
            Dict with scaling results and previous state for restoration
        """
        # Use typed variables for type checker narrowing
        errors: list[str] = []
        result: dict[str, Any] = {
            "success": True,
            "previous_workers": None,
            "current_workers": None,
            "optillm_scaled": False,
            "errors": errors,
        }

        if self._optillm:
            try:
                # Save current worker count for later restoration
                result["previous_workers"] = self._optillm._configured_workers

                # Scale to 1 worker during large model loading
                success = await self._optillm.scale_workers(1)
                result["optillm_scaled"] = success
                result["current_workers"] = 1 if success else result["previous_workers"]

                if success:
                    logger.info(
                        f"Scaled optillm workers from {result['previous_workers']} to 1 "
                        f"for large model deployment on GPUs {target_gpus}"
                    )
                else:
                    errors.append("Failed to scale optillm workers")
                    result["success"] = False

            except Exception as e:
                logger.error(f"Error scaling optillm for large model: {e}")
                errors.append(str(e))
                result["success"] = False

        return result

    async def restore_normal_operations(self, previous_workers: int = 4) -> dict[str, Any]:
        """Restore full worker count after large model finishes.

        Call this after the large model task completes to restore
        normal optillm throughput.

        Args:
            previous_workers: Worker count to restore (default 4)

        Returns:
            Dict with restoration results
        """
        # Use typed variables for type checker narrowing
        errors: list[str] = []
        result: dict[str, Any] = {
            "success": True,
            "previous_workers": 1,
            "current_workers": previous_workers,
            "optillm_scaled": False,
            "errors": errors,
        }

        if self._optillm:
            try:
                result["previous_workers"] = self._optillm._configured_workers
                success = await self._optillm.scale_workers(previous_workers)
                result["optillm_scaled"] = success
                result["current_workers"] = (
                    previous_workers if success else result["previous_workers"]
                )

                if success:
                    logger.info(f"Restored optillm workers to {previous_workers}")
                else:
                    errors.append("Failed to restore optillm workers")
                    result["success"] = False

            except Exception as e:
                logger.error(f"Error restoring optillm workers: {e}")
                errors.append(str(e))
                result["success"] = False

        return result

    async def reload_optillm(self) -> dict[str, Any]:
        """Reload optillm configuration via SIGHUP.

        Gracefully restarts workers to pick up configuration changes
        without losing in-flight requests.

        Returns:
            Dict with reload result
        """
        result = {
            "success": False,
            "reload_count": 0,
            "error": None,
        }

        if not self._optillm:
            result["error"] = "optillm controller not available"
            return result

        try:
            success = await self._optillm.reload()
            result["success"] = success
            result["reload_count"] = self._optillm._reload_count

            if success:
                logger.info("optillm configuration reloaded")
            else:
                result["error"] = "reload returned false"

        except Exception as e:
            logger.error(f"Error reloading optillm: {e}")
            result["error"] = str(e)

        return result

    async def update_optillm_technique(self, technique: str) -> dict[str, Any]:
        """Update optillm default technique and reload.

        Args:
            technique: New technique (e.g., "cot_reflection", "bon", "moa")

        Returns:
            Dict with update result
        """
        result = {
            "success": False,
            "previous_technique": None,
            "current_technique": technique,
            "error": None,
        }

        if not self._optillm:
            result["error"] = "optillm controller not available"
            return result

        try:
            result["previous_technique"] = self._optillm._default_technique.value
            success = await self._optillm.update_technique(technique)
            result["success"] = success

            if not success:
                result["error"] = "technique update failed"
                result["current_technique"] = result["previous_technique"]

        except Exception as e:
            logger.error(f"Error updating optillm technique: {e}")
            result["error"] = str(e)

        return result

    def get_optillm_status(self) -> Optional[dict[str, Any]]:
        """Get optillm controller status.

        Returns:
            Status dict or None if optillm not available
        """
        if not self._optillm:
            return None
        return self._optillm.get_status()

    # ─────────────────────────────────────────────────────────────────────────
    # Status
    # ─────────────────────────────────────────────────────────────────────────

    def get_status(self) -> dict[str, Any]:
        """Get comprehensive orchestrator status.

        Returns:
            Status dict with endpoints, GPUs, and health
        """
        endpoints = {}
        for alias, proc in self._vllm._processes.items():
            message, progress = self._vllm.get_startup_progress(alias)
            endpoints[alias] = {
                "model": proc.model,
                "port": proc.port,
                "gpu_ids": proc.gpu_ids,
                "status": proc.status.value,
                "pid": proc.pid,
                "startup_progress": progress,
                "startup_message": message,
                "requests_served": proc.requests_served,
            }

        return {
            "running": self._running,
            "endpoints": endpoints,
            "total_running": sum(
                1
                for p in self._vllm._processes.values()
                if p.status == ProcessStatus.HEALTHY
            ),
            "gpu_utilization": self._gpu_utilization,
            "is_idle": self.is_gpu_idle(),
            "last_health_check": (
                self._last_health_check.isoformat()
                if self._last_health_check
                else None
            ),
            "resources": self.resource_manager.get_summary(),
        }


# =============================================================================
# Module-level singleton factory
# =============================================================================

_orchestrator_service: OrchestratorService | None = None


def get_orchestrator_service() -> OrchestratorService:
    """Get the global OrchestratorService singleton.

    The singleton must be set by the engine server via set_orchestrator_service()
    during startup. This function is used by components that need orchestrator
    access outside of the main engine server context (e.g., HealthObserver).

    Returns:
        OrchestratorService instance

    Raises:
        RuntimeError: If the service has not been registered
    """
    global _orchestrator_service
    if _orchestrator_service is None:
        raise RuntimeError(
            "OrchestratorService not initialized.\n"
            "  The engine server must call set_orchestrator_service() during startup.\n"
            "  Guru Meditation: #ORCH.00000001.SVCNOTINIT\n"
            "  Fix: Ensure the engine is running: devenv tasks run restart:clean"
        )
    return _orchestrator_service


def set_orchestrator_service(service: OrchestratorService) -> None:
    """Set the global OrchestratorService singleton.

    Used by the engine server to register its orchestrator instance.

    Args:
        service: The OrchestratorService instance to use globally
    """
    global _orchestrator_service
    _orchestrator_service = service
