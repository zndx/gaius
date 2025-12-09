"""Intelligent inference scheduler using OR-Tools.

.. deprecated::
    This module is DEPRECATED. Use gRPC engine instead:

        from gaius.client.engine_proxy import get_scheduler_proxy
        scheduler = await get_scheduler_proxy()
        result = await scheduler.complete(prompt="Hello")

    The gRPC engine provides:
    - Capability-based routing (not hardcoded model names)
    - Centralized auth/authz
    - Proper resource management via agents.conf

    This client-side scheduler bypasses the gRPC security boundary and uses
    hardcoded model names that may not exist on the current vLLM deployment.

Core capability for Gaius that manages inference jobs across GPU endpoints.
Provides:
- Optimal job scheduling with OR-Tools CP-SAT
- Background job execution
- Real-time status updates
- Event-driven job lifecycle
- Persistence for job history

Usage (DEPRECATED):
    from gaius.inference.scheduler import get_scheduler, Job, JobPriority

    scheduler = get_scheduler()

    # Submit and execute a job
    job = Job(
        model="Qwen/QwQ-32B",
        messages=[{"role": "user", "content": "Hello"}],
        priority=JobPriority.HIGH,
    )
    result = await scheduler.submit(job)
    print(result.content)

    # Submit without waiting (background execution)
    job_id = await scheduler.submit_async(job)
    # ... later ...
    result = await scheduler.get_result(job_id)

    # Schedule swarm with optimal distribution
    results = await scheduler.run_swarm(
        domain="pension risk",
        roles=[AgentRole.LEADER, AgentRole.RISK, ...],
    )
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Callable, Awaitable
from collections import defaultdict
import asyncio
import logging
import json

try:
    from ortools.sat.python import cp_model
    ORTOOLS_AVAILABLE = True
except ImportError:
    ORTOOLS_AVAILABLE = False

try:
    from openai import AsyncOpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False

logger = logging.getLogger(__name__)


class JobPriority(Enum):
    """Job priority levels."""
    CRITICAL = 0   # Leader synthesis, user-facing
    HIGH = 1       # Swarm agents
    NORMAL = 2     # Background tasks
    LOW = 3        # Batch processing


class JobStatus(Enum):
    """Job execution status."""
    PENDING = "pending"
    SCHEDULED = "scheduled"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class Job:
    """An inference job to be scheduled."""

    id: str = ""
    model: str = ""
    messages: list = field(default_factory=list)
    priority: JobPriority = JobPriority.NORMAL

    # Timing constraints
    deadline_ms: int = 30000  # Max acceptable latency
    estimated_tokens: int = 500  # Estimated output tokens

    # Affinity
    preferred_endpoint: str | None = None
    role: str | None = None  # Agent role if applicable

    # State
    status: JobStatus = JobStatus.PENDING
    created_at: datetime = field(default_factory=datetime.now)
    scheduled_at: datetime | None = None
    completed_at: datetime | None = None

    # Result
    result: Any = None
    error: str | None = None

    def __post_init__(self):
        if not self.id:
            import uuid
            self.id = str(uuid.uuid4())[:8]


@dataclass
class EndpointState:
    """Current state of a GPU endpoint."""

    name: str
    url: str
    gpus: list[int] = field(default_factory=list)

    # Current model loaded
    current_model: str | None = None
    models_available: list[str] = field(default_factory=list)

    # Capacity
    vram_total_gb: float = 24.0
    vram_used_gb: float = 0.0
    queue_depth: int = 0
    max_queue_depth: int = 10

    # Performance estimates
    tokens_per_second: float = 50.0  # Estimated throughput
    model_load_time_ms: int = 30000  # Cold start penalty

    # Health
    healthy: bool = True
    last_health_check: datetime = field(default_factory=datetime.now)


@dataclass
class Assignment:
    """Scheduled assignment of a job to an endpoint."""

    job: Job
    endpoint: str
    estimated_start_ms: int = 0
    estimated_duration_ms: int = 0
    requires_model_load: bool = False
    model_load_time_ms: int = 0


class InferenceScheduler:
    """Schedules inference jobs across GPU endpoints.

    Uses OR-Tools CP-SAT for optimal scheduling when available,
    falls back to priority queue + heuristics otherwise.
    """

    def __init__(self):
        self._endpoints: dict[str, EndpointState] = {}
        self._job_queue: list[tuple[int, datetime, Job]] = []  # Priority queue
        self._running_jobs: dict[str, Job] = {}
        self._lock = asyncio.Lock()

        # Load endpoint config
        self._load_endpoints()

    def _load_endpoints(self) -> None:
        """Load endpoint configuration."""
        try:
            from ..core.config import get_config

            config = get_config()
            inference = config._raw.get("gaius", {}).get("inference", {})
            endpoints_raw = inference.get("endpoints", {})

            for name, ep in endpoints_raw.items():
                if isinstance(ep, dict):
                    self._endpoints[name] = EndpointState(
                        name=name,
                        url=ep.get("url", ""),
                        gpus=ep.get("gpus", []),
                        models_available=ep.get("models", []),
                        current_model=ep.get("models", [None])[0] if ep.get("models") else None,
                    )
        except Exception:
            # LEGACY_FALLBACK: Single default endpoint when config loading fails
            # In agent-first mode, engine manages endpoints; this is a last resort
            logger.warning("LEGACY_FALLBACK: Using default endpoint - prefer engine proxy")
            self._endpoints["default"] = EndpointState(
                name="default",
                url="http://localhost:8080/v1",  # orchestrator endpoint
            )

    def _estimate_duration(self, job: Job, endpoint: EndpointState) -> int:
        """Estimate job duration in milliseconds."""
        # Base: token generation time
        tokens = job.estimated_tokens
        tps = endpoint.tokens_per_second
        generation_ms = (tokens / tps) * 1000

        # Add overhead for prompt processing
        overhead_ms = 500

        return int(generation_ms + overhead_ms)

    def _compute_model_load_penalty(self, job: Job, endpoint: EndpointState) -> int:
        """Compute cold start penalty if model needs loading."""
        if job.model and job.model != endpoint.current_model:
            if job.model not in endpoint.models_available:
                return endpoint.model_load_time_ms * 2  # Download + load
            return endpoint.model_load_time_ms
        return 0

    async def schedule(self, job: Job) -> Assignment:
        """Schedule a single job to the best endpoint.

        Uses heuristic scoring for single jobs.
        """
        async with self._lock:
            best_endpoint = None
            best_score = float('inf')
            best_load_time = 0

            for name, endpoint in self._endpoints.items():
                if not endpoint.healthy:
                    continue

                if endpoint.queue_depth >= endpoint.max_queue_depth:
                    continue

                # Score = estimated total time (lower is better)
                load_time = self._compute_model_load_penalty(job, endpoint)
                duration = self._estimate_duration(job, endpoint)
                queue_wait = endpoint.queue_depth * 2000  # Rough estimate

                # Priority bonus (higher priority = lower score adjustment)
                priority_factor = 1.0 - (job.priority.value * 0.1)

                # Affinity bonus
                affinity_bonus = 0
                if job.preferred_endpoint == name:
                    affinity_bonus = -5000
                if job.model and job.model == endpoint.current_model:
                    affinity_bonus = -3000  # Warm model bonus

                score = (load_time + duration + queue_wait) * priority_factor + affinity_bonus

                if score < best_score:
                    best_score = score
                    best_endpoint = name
                    best_load_time = load_time

            if best_endpoint is None:
                raise RuntimeError("No healthy endpoints available")

            endpoint = self._endpoints[best_endpoint]
            endpoint.queue_depth += 1

            return Assignment(
                job=job,
                endpoint=best_endpoint,
                estimated_start_ms=endpoint.queue_depth * 2000,
                estimated_duration_ms=self._estimate_duration(job, endpoint),
                requires_model_load=best_load_time > 0,
                model_load_time_ms=best_load_time,
            )

    async def schedule_batch(self, jobs: list[Job]) -> list[Assignment]:
        """Schedule a batch of jobs optimally.

        Uses OR-Tools CP-SAT solver for optimal assignment when available.
        """
        if not jobs:
            return []

        if len(jobs) == 1:
            return [await self.schedule(jobs[0])]

        if ORTOOLS_AVAILABLE and len(jobs) >= 3:
            return await self._schedule_batch_ortools(jobs)
        else:
            return await self._schedule_batch_greedy(jobs)

    async def _schedule_batch_greedy(self, jobs: list[Job]) -> list[Assignment]:
        """Greedy batch scheduling - schedule highest priority first."""
        # Sort by priority
        sorted_jobs = sorted(jobs, key=lambda j: (j.priority.value, j.created_at))
        assignments = []
        for job in sorted_jobs:
            assignment = await self.schedule(job)
            assignments.append(assignment)
        return assignments

    async def _schedule_batch_ortools(self, jobs: list[Job]) -> list[Assignment]:
        """Optimal batch scheduling using OR-Tools CP-SAT.

        Minimizes makespan (total completion time) while respecting:
        - Endpoint capacity constraints
        - Model loading penalties
        - Priority ordering
        """
        model = cp_model.CpModel()

        endpoints = [e for e in self._endpoints.values() if e.healthy]
        if not endpoints:
            raise RuntimeError("No healthy endpoints available")

        n_jobs = len(jobs)
        n_endpoints = len(endpoints)

        # Decision variables: x[j][e] = 1 if job j assigned to endpoint e
        x = {}
        for j in range(n_jobs):
            for e in range(n_endpoints):
                x[j, e] = model.NewBoolVar(f'x_{j}_{e}')

        # Constraint: Each job assigned to exactly one endpoint
        for j in range(n_jobs):
            model.Add(sum(x[j, e] for e in range(n_endpoints)) == 1)

        # Constraint: Endpoint capacity (queue depth)
        for e in range(n_endpoints):
            endpoint = endpoints[e]
            available_capacity = endpoint.max_queue_depth - endpoint.queue_depth
            model.Add(sum(x[j, e] for j in range(n_jobs)) <= available_capacity)

        # Compute costs for objective
        # cost[j][e] = estimated total time for job j on endpoint e
        costs = {}
        for j in range(n_jobs):
            job = jobs[j]
            for e in range(n_endpoints):
                endpoint = endpoints[e]
                load_time = self._compute_model_load_penalty(job, endpoint)
                duration = self._estimate_duration(job, endpoint)

                # Priority weight (critical jobs weighted 4x)
                priority_weight = 4 - job.priority.value

                # Affinity bonus (reduce cost for preferred endpoint)
                affinity = 0
                if job.preferred_endpoint == endpoint.name:
                    affinity = -1000
                if job.model == endpoint.current_model:
                    affinity = -500

                costs[j, e] = (load_time + duration + affinity) * priority_weight

        # Objective: Minimize total weighted cost
        objective_terms = []
        for j in range(n_jobs):
            for e in range(n_endpoints):
                objective_terms.append(costs[j, e] * x[j, e])
        model.Minimize(sum(objective_terms))

        # Solve
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = 1.0  # Quick solve
        status = solver.Solve(model)

        if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            # Fallback to greedy
            return await self._schedule_batch_greedy(jobs)

        # Extract assignments
        assignments = []
        async with self._lock:
            for j in range(n_jobs):
                for e in range(n_endpoints):
                    if solver.Value(x[j, e]) == 1:
                        endpoint = endpoints[e]
                        job = jobs[j]

                        load_time = self._compute_model_load_penalty(job, endpoint)
                        endpoint.queue_depth += 1

                        assignments.append(Assignment(
                            job=job,
                            endpoint=endpoint.name,
                            estimated_start_ms=endpoint.queue_depth * 2000,
                            estimated_duration_ms=self._estimate_duration(job, endpoint),
                            requires_model_load=load_time > 0,
                            model_load_time_ms=load_time,
                        ))
                        break

        return assignments

    async def schedule_swarm(
        self,
        roles: list,
        domain: str,
        context: str = "",
    ) -> list[Assignment]:
        """Schedule a complete swarm round.

        Optimizes agent distribution across endpoints based on
        role preferences and model requirements.
        """
        from ..agents.roles import get_role

        jobs = []
        for role in roles:
            role_def = get_role(role)

            # Build prompt
            prompt = role_def.get_prompt(domain, context)

            job = Job(
                model=role_def.preferred_model_id or "",
                messages=[{"role": "user", "content": prompt}],
                priority=JobPriority.HIGH,
                estimated_tokens=role_def.max_tokens,
                role=role_def.name,
            )
            jobs.append(job)

        return await self.schedule_batch(jobs)

    def update_endpoint_state(
        self,
        endpoint: str,
        queue_depth: int | None = None,
        current_model: str | None = None,
        healthy: bool | None = None,
    ) -> None:
        """Update endpoint state after job completion or health check."""
        if endpoint in self._endpoints:
            ep = self._endpoints[endpoint]
            if queue_depth is not None:
                ep.queue_depth = queue_depth
            if current_model is not None:
                ep.current_model = current_model
            if healthy is not None:
                ep.healthy = healthy
                ep.last_health_check = datetime.now()

    def get_status(self) -> dict[str, Any]:
        """Get scheduler status summary."""
        return {
            "endpoints": {
                name: {
                    "healthy": ep.healthy,
                    "current_model": ep.current_model,
                    "queue_depth": ep.queue_depth,
                    "max_queue_depth": ep.max_queue_depth,
                    "gpus": ep.gpus,
                }
                for name, ep in self._endpoints.items()
            },
            "pending_jobs": len(self._job_queue),
            "running_jobs": len(self._running_jobs),
            "ortools_available": ORTOOLS_AVAILABLE,
        }


# ═══════════════════════════════════════════════════════════════════════════════
# Event System
# ═══════════════════════════════════════════════════════════════════════════════


class JobEvent(Enum):
    """Job lifecycle events."""
    SUBMITTED = "submitted"
    SCHEDULED = "scheduled"
    STARTED = "started"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class JobEventData:
    """Data for a job event."""
    event: JobEvent
    job: Job
    timestamp: datetime = field(default_factory=datetime.now)
    endpoint: str | None = None
    error: str | None = None
    result: Any = None


# Event callback type
EventCallback = Callable[[JobEventData], Awaitable[None]]


# ═══════════════════════════════════════════════════════════════════════════════
# Job Result
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class JobResult:
    """Result of a completed job."""
    job_id: str
    status: JobStatus
    content: str = ""
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0
    endpoint: str = ""
    error: str | None = None


# ═══════════════════════════════════════════════════════════════════════════════
# Scheduler Service (Enhanced)
# ═══════════════════════════════════════════════════════════════════════════════


class SchedulerService:
    """Full-featured scheduler service with execution and event support.

    This is the core scheduler capability for Gaius, providing:
    - Job submission and execution
    - Background processing
    - Event notifications
    - Swarm orchestration
    - Health monitoring
    - GPU orchestration (on-demand model loading)
    - Job persistence (crash recovery)
    - Auto-recovery (4-level escalation)
    """

    def __init__(self):
        self._scheduler = InferenceScheduler()
        self._clients: dict[str, AsyncOpenAI] = {}
        self._job_results: dict[str, JobResult] = {}
        self._job_futures: dict[str, asyncio.Future] = {}
        self._event_handlers: dict[JobEvent, list[EventCallback]] = defaultdict(list)
        self._worker_task: asyncio.Task | None = None
        self._health_task: asyncio.Task | None = None
        self._running = False
        self._lock = asyncio.Lock()

        # Metrics
        self._metrics = {
            "jobs_submitted": 0,
            "jobs_completed": 0,
            "jobs_failed": 0,
            "total_tokens": 0,
            "total_latency_ms": 0,
        }

        # GPU Orchestrator components (initialized in start())
        self._orchestrator = None
        self._health_monitor = None
        self._recovery_manager = None
        self._persistence = None

        self._init_clients()

    def _init_clients(self) -> None:
        """Initialize OpenAI clients for each endpoint."""
        if not OPENAI_AVAILABLE:
            return

        for name, endpoint in self._scheduler._endpoints.items():
            try:
                self._clients[name] = AsyncOpenAI(
                    api_key="sk-vllm",
                    base_url=endpoint.url,
                    timeout=60,
                )
            except Exception as e:
                logger.warning(f"Failed to init client for {name}: {e}")

        # Add optillm as fallback client
        try:
            # Try HOCON config first, fall back to env/defaults
            api_key = "sk-optillm"
            optillm_url = "http://localhost:8088/v1"  # optillm proxy when running
            model = "mistralai/Mistral-7B-Instruct-v0.3"

            try:
                from ..core.config import get_config
                app_config = get_config()
                optillm_cfg = app_config.inference.optillm
                api_key = optillm_cfg.api_key or api_key
                optillm_url = optillm_cfg.url or optillm_url
                model = app_config.inference.model or model
            except Exception:
                # Fall back to env vars
                import os
                api_key = os.getenv("OPTILLM_API_KEY", api_key)
                optillm_url = os.getenv("GAIUS_OPTILLM_URL", optillm_url)

            self._clients["optillm"] = AsyncOpenAI(
                api_key=api_key,
                base_url=optillm_url,
                timeout=120,
            )
            self._optillm_model = model
            logger.info(f"Optillm fallback configured: {optillm_url}")
        except Exception as e:
            logger.warning(f"Failed to init optillm fallback: {e}")

    # ─────────────────────────────────────────────────────────────────────────
    # Event System
    # ─────────────────────────────────────────────────────────────────────────

    def on(self, event: JobEvent, callback: EventCallback) -> None:
        """Register an event handler."""
        self._event_handlers[event].append(callback)

    def off(self, event: JobEvent, callback: EventCallback) -> None:
        """Unregister an event handler."""
        if callback in self._event_handlers[event]:
            self._event_handlers[event].remove(callback)

    async def _emit(self, event_data: JobEventData) -> None:
        """Emit an event to all registered handlers."""
        for handler in self._event_handlers[event_data.event]:
            try:
                await handler(event_data)
            except Exception as e:
                logger.error(f"Event handler error: {e}")

    # ─────────────────────────────────────────────────────────────────────────
    # Job Submission
    # ─────────────────────────────────────────────────────────────────────────

    async def submit(self, job: Job) -> JobResult:
        """Submit a job and wait for completion.

        Args:
            job: Job to execute

        Returns:
            JobResult with response content
        """
        job_id = await self.submit_async(job)
        return await self.wait_for_result(job_id)

    async def submit_async(self, job: Job) -> str:
        """Submit a job for background execution.

        Args:
            job: Job to execute

        Returns:
            Job ID for tracking
        """
        async with self._lock:
            self._metrics["jobs_submitted"] += 1

            # Persist job to database for crash recovery
            if self._persistence and self._persistence.connected:
                try:
                    persisted_id = await self._persistence.save_job(job)
                    if not job.id:
                        job.id = persisted_id
                except Exception as e:
                    logger.warning(f"Failed to persist job: {e}")

            # Schedule the job
            assignment = await self._scheduler.schedule(job)
            job.status = JobStatus.SCHEDULED
            job.scheduled_at = datetime.now()

            # Update status in database
            if self._persistence and self._persistence.connected:
                try:
                    await self._persistence.update_status(
                        job.id, JobStatus.SCHEDULED, assignment.endpoint
                    )
                except Exception as e:
                    logger.warning(f"Failed to update job status: {e}")

            # Create future for result
            future = asyncio.get_event_loop().create_future()
            self._job_futures[job.id] = future

            # Emit event
            await self._emit(JobEventData(
                event=JobEvent.SUBMITTED,
                job=job,
                endpoint=assignment.endpoint,
            ))

            # Start execution
            asyncio.create_task(self._execute_job(job, assignment))

            return job.id

    async def submit_batch(self, jobs: list[Job]) -> list[str]:
        """Submit multiple jobs with optimal scheduling.

        Args:
            jobs: Jobs to execute

        Returns:
            List of job IDs
        """
        assignments = await self._scheduler.schedule_batch(jobs)

        job_ids = []
        for assignment in assignments:
            job = assignment.job
            job.status = JobStatus.SCHEDULED
            job.scheduled_at = datetime.now()

            future = asyncio.get_event_loop().create_future()
            self._job_futures[job.id] = future
            job_ids.append(job.id)

            await self._emit(JobEventData(
                event=JobEvent.SUBMITTED,
                job=job,
                endpoint=assignment.endpoint,
            ))

            asyncio.create_task(self._execute_job(job, assignment))

        return job_ids

    # ─────────────────────────────────────────────────────────────────────────
    # Job Execution
    # ─────────────────────────────────────────────────────────────────────────

    async def _execute_job(self, job: Job, assignment: Assignment) -> None:
        """Execute a job on its assigned endpoint, with optillm fallback."""
        start_time = datetime.now()
        result = JobResult(
            job_id=job.id,
            status=JobStatus.RUNNING,
            endpoint=assignment.endpoint,
        )

        try:
            job.status = JobStatus.RUNNING

            # Persist status update
            if self._persistence and self._persistence.connected:
                try:
                    await self._persistence.update_status(
                        job.id, JobStatus.RUNNING, assignment.endpoint
                    )
                except Exception as e:
                    logger.warning(f"Failed to persist job status: {e}")

            # On-demand model loading via orchestrator
            if self._orchestrator and job.model:
                try:
                    endpoint = await self._orchestrator.ensure_model_loaded(job.model)
                    if endpoint and endpoint != assignment.endpoint:
                        logger.info(
                            f"Model {job.model} loaded on {endpoint}, "
                            f"updating assignment from {assignment.endpoint}"
                        )
                        assignment.endpoint = endpoint
                except Exception as e:
                    logger.warning(f"On-demand model loading failed: {e}")

            await self._emit(JobEventData(
                event=JobEvent.STARTED,
                job=job,
                endpoint=assignment.endpoint,
            ))

            # Prepare messages
            messages = []
            for m in job.messages:
                if isinstance(m, dict):
                    messages.append(m)
                elif hasattr(m, "role"):
                    messages.append({"role": m.role, "content": m.content})

            # Try primary endpoint, fall back to optillm
            response = None
            used_endpoint = assignment.endpoint
            model = job.model or "default"

            # Try assigned endpoint first
            client = self._clients.get(assignment.endpoint)
            if client is not None:
                try:
                    response = await client.chat.completions.create(
                        model=model,
                        messages=messages,
                        temperature=0.7,
                        max_tokens=job.estimated_tokens or 1024,
                    )
                except Exception as primary_error:
                    logger.warning(f"Primary endpoint {assignment.endpoint} failed: {primary_error}")
                    # Mark endpoint unhealthy
                    self._scheduler.update_endpoint_state(assignment.endpoint, healthy=False)

            # Fallback to optillm if primary failed
            if response is None and "optillm" in self._clients:
                logger.info(f"Falling back to optillm for job {job.id}")
                client = self._clients["optillm"]
                used_endpoint = "optillm"
                # Use configured model for optillm
                fallback_model = getattr(self, "_optillm_model", "default")
                response = await client.chat.completions.create(
                    model=fallback_model,
                    messages=messages,
                    temperature=0.7,
                    max_tokens=job.estimated_tokens or 1024,
                )

            if response is None:
                raise RuntimeError(f"No available endpoints for job {job.id}")

            # Extract result
            choice = response.choices[0]
            usage = response.usage

            result.status = JobStatus.COMPLETED
            result.content = choice.message.content or ""
            result.model = response.model
            result.endpoint = used_endpoint
            result.input_tokens = usage.prompt_tokens if usage else 0
            result.output_tokens = usage.completion_tokens if usage else 0

            job.status = JobStatus.COMPLETED
            job.completed_at = datetime.now()
            job.result = result.content

            self._metrics["jobs_completed"] += 1
            self._metrics["total_tokens"] += result.input_tokens + result.output_tokens

        except Exception as e:
            result.status = JobStatus.FAILED
            result.error = str(e)
            job.status = JobStatus.FAILED
            job.error = str(e)
            job.completed_at = datetime.now()

            self._metrics["jobs_failed"] += 1

            # Trigger recovery if we have a recovery manager
            if self._recovery_manager:
                try:
                    from .recovery import RecoveryLevel
                    level = self._recovery_manager.determine_recovery_level(
                        consecutive_failures=1,
                        error=e,
                    )
                    if level >= RecoveryLevel.WARM_RESTART:
                        asyncio.create_task(
                            self._recovery_manager.execute_recovery(
                                assignment.endpoint, level
                            )
                        )
                except Exception as recovery_error:
                    logger.error(f"Recovery trigger failed: {recovery_error}")

            await self._emit(JobEventData(
                event=JobEvent.FAILED,
                job=job,
                endpoint=assignment.endpoint,
                error=str(e),
            ))

        finally:
            # Calculate latency
            result.latency_ms = int((datetime.now() - start_time).total_seconds() * 1000)
            self._metrics["total_latency_ms"] += result.latency_ms

            # Update endpoint state
            self._scheduler.update_endpoint_state(
                assignment.endpoint,
                queue_depth=max(0, self._scheduler._endpoints[assignment.endpoint].queue_depth - 1),
            )

            # Persist result to database
            if self._persistence and self._persistence.connected:
                try:
                    await self._persistence.save_result(job.id, result)
                except Exception as e:
                    logger.warning(f"Failed to persist job result: {e}")

            # Store result and resolve future
            self._job_results[job.id] = result

            if job.id in self._job_futures:
                future = self._job_futures[job.id]
                if not future.done():
                    future.set_result(result)

            if result.status == JobStatus.COMPLETED:
                await self._emit(JobEventData(
                    event=JobEvent.COMPLETED,
                    job=job,
                    endpoint=assignment.endpoint,
                    result=result,
                ))

    # ─────────────────────────────────────────────────────────────────────────
    # Result Retrieval
    # ─────────────────────────────────────────────────────────────────────────

    async def wait_for_result(self, job_id: str, timeout: float = 60.0) -> JobResult:
        """Wait for a job to complete and return its result.

        Args:
            job_id: Job ID to wait for
            timeout: Maximum wait time in seconds

        Returns:
            JobResult

        Raises:
            asyncio.TimeoutError: If timeout exceeded
            KeyError: If job not found
        """
        if job_id in self._job_results:
            return self._job_results[job_id]

        if job_id not in self._job_futures:
            raise KeyError(f"Unknown job: {job_id}")

        future = self._job_futures[job_id]
        return await asyncio.wait_for(future, timeout=timeout)

    def get_result(self, job_id: str) -> JobResult | None:
        """Get result for a completed job (non-blocking).

        Args:
            job_id: Job ID

        Returns:
            JobResult if completed, None if still running
        """
        return self._job_results.get(job_id)

    # ─────────────────────────────────────────────────────────────────────────
    # Swarm Execution
    # ─────────────────────────────────────────────────────────────────────────

    async def run_swarm(
        self,
        domain: str,
        roles: list | None = None,
        context: str = "",
    ) -> dict[str, JobResult]:
        """Run a complete swarm analysis with optimal scheduling.

        Args:
            domain: Domain to analyze
            roles: Agent roles to include (default: all)
            context: Additional context

        Returns:
            Dict mapping role name to JobResult
        """
        from ..agents.roles import AgentRole, get_role

        if roles is None:
            roles = list(AgentRole)

        # Create jobs for each role
        jobs = []
        for role in roles:
            role_def = get_role(role)
            prompt = role_def.get_prompt(domain, context)

            job = Job(
                model=role_def.preferred_model_id or "",
                messages=[{"role": "user", "content": prompt}],
                priority=JobPriority.HIGH,
                estimated_tokens=role_def.max_tokens,
                role=role_def.name,
            )
            jobs.append(job)

        # Submit all jobs with optimal scheduling
        job_ids = await self.submit_batch(jobs)

        # Wait for all results
        results = {}
        for job, job_id in zip(jobs, job_ids):
            try:
                result = await self.wait_for_result(job_id, timeout=120.0)
                results[job.role] = result
            except asyncio.TimeoutError:
                results[job.role] = JobResult(
                    job_id=job_id,
                    status=JobStatus.FAILED,
                    error="Timeout",
                )

        return results

    # ─────────────────────────────────────────────────────────────────────────
    # Health Monitoring
    # ─────────────────────────────────────────────────────────────────────────

    async def health_check(self) -> dict[str, bool]:
        """Check health of all endpoints."""
        import httpx

        results = {}

        async with httpx.AsyncClient() as client:
            for name, endpoint in self._scheduler._endpoints.items():
                try:
                    base_url = endpoint.url.rstrip("/v1")
                    r = await client.get(f"{base_url}/v1/models", timeout=5)
                    healthy = r.status_code == 200
                    endpoint.healthy = healthy
                    results[name] = healthy
                except Exception:
                    endpoint.healthy = False
                    results[name] = False

        return results

    async def _health_loop(self, interval: float = 30.0) -> None:
        """Background health check loop."""
        while self._running:
            try:
                await self.health_check()
            except Exception as e:
                logger.error(f"Health check error: {e}")
            await asyncio.sleep(interval)

    # ─────────────────────────────────────────────────────────────────────────
    # Lifecycle
    # ─────────────────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Start the scheduler service."""
        if self._running:
            return

        self._running = True

        # Initialize GPU orchestrator components
        await self._init_orchestrator_components()

        # Restore pending jobs from database
        await self._restore_pending_jobs()

        # Start health check loop
        self._health_task = asyncio.create_task(self._health_loop())

        logger.info("Scheduler service started")

    async def _init_orchestrator_components(self) -> None:
        """Initialize GPU orchestrator, health monitor, recovery manager, and persistence.

        Prefers engine client (agent-first architecture) when available.
        Falls back to legacy orchestrator for standalone mode.
        """
        try:
            from ..client.engine_proxy import use_engine_proxy

            if use_engine_proxy():
                # Engine is running - it manages GPU orchestration
                logger.info("Using engine for GPU orchestration (agent-first mode)")
                self._orchestrator = None  # Engine handles this
            else:
                # Fallback to legacy standalone orchestrator
                logger.warning("LEGACY_FALLBACK: InferenceScheduler using legacy orchestrator - tech debt")
                from .orchestrator import get_orchestrator
                self._orchestrator = get_orchestrator()
                await self._orchestrator.start()
                logger.info("GPU orchestrator initialized (standalone mode)")
        except Exception as e:
            logger.warning(f"GPU orchestrator not available: {e}")

        try:
            from .health import get_health_monitor
            self._health_monitor = get_health_monitor()
            logger.info(f"GPU health monitor initialized: {self._health_monitor.device_count} GPUs")
        except Exception as e:
            logger.warning(f"GPU health monitor not available: {e}")

        try:
            if self._orchestrator:
                from .recovery import RecoveryManager
                self._recovery_manager = RecoveryManager(self._orchestrator)
                logger.info("Recovery manager initialized")
        except Exception as e:
            logger.warning(f"Recovery manager not available: {e}")

        try:
            from .persistence import get_persistence
            self._persistence = await get_persistence()
            if self._persistence.connected:
                logger.info("Job persistence initialized (PostgreSQL)")
            else:
                logger.warning("Job persistence: database not connected")
        except Exception as e:
            logger.warning(f"Job persistence not available: {e}")

    async def _restore_pending_jobs(self) -> None:
        """Restore pending jobs from database after restart."""
        if not self._persistence or not self._persistence.connected:
            return

        try:
            pending = await self._persistence.get_pending_jobs()
            if pending:
                logger.info(f"Restoring {len(pending)} pending jobs from database")
                for job in pending:
                    # Re-submit without persisting again
                    assignment = await self._scheduler.schedule(job)
                    job.status = JobStatus.SCHEDULED
                    job.scheduled_at = datetime.now()

                    future = asyncio.get_event_loop().create_future()
                    self._job_futures[job.id] = future

                    asyncio.create_task(self._execute_job(job, assignment))
        except Exception as e:
            logger.error(f"Failed to restore pending jobs: {e}")

    async def stop(self) -> None:
        """Stop the scheduler service."""
        self._running = False

        if self._health_task:
            self._health_task.cancel()
            try:
                await self._health_task
            except asyncio.CancelledError:
                pass

        # Stop GPU orchestrator
        if self._orchestrator:
            try:
                await self._orchestrator.stop()
            except Exception as e:
                logger.error(f"Error stopping orchestrator: {e}")

        # Disconnect persistence
        if self._persistence:
            try:
                await self._persistence.disconnect()
            except Exception as e:
                logger.error(f"Error disconnecting persistence: {e}")

        logger.info("Scheduler service stopped")

    # ─────────────────────────────────────────────────────────────────────────
    # Status
    # ─────────────────────────────────────────────────────────────────────────

    def get_status(self) -> dict[str, Any]:
        """Get comprehensive scheduler status."""
        return {
            "running": self._running,
            "endpoints": self._scheduler.get_status()["endpoints"],
            "pending_jobs": len(self._job_futures) - len(self._job_results),
            "completed_jobs": len(self._job_results),
            "metrics": self._metrics.copy(),
            "ortools_available": ORTOOLS_AVAILABLE,
        }

    def get_metrics(self) -> dict[str, Any]:
        """Get scheduler metrics."""
        metrics = self._metrics.copy()

        # Compute averages
        if metrics["jobs_completed"] > 0:
            metrics["avg_latency_ms"] = metrics["total_latency_ms"] / metrics["jobs_completed"]
            metrics["avg_tokens"] = metrics["total_tokens"] / metrics["jobs_completed"]
        else:
            metrics["avg_latency_ms"] = 0
            metrics["avg_tokens"] = 0

        return metrics


# ═══════════════════════════════════════════════════════════════════════════════
# Module-level Singletons
# ═══════════════════════════════════════════════════════════════════════════════

_scheduler: InferenceScheduler | None = None
_service: SchedulerService | None = None


def get_scheduler() -> InferenceScheduler:
    """Get or create the inference scheduler singleton."""
    global _scheduler
    if _scheduler is None:
        _scheduler = InferenceScheduler()
    return _scheduler


def get_scheduler_service() -> SchedulerService:
    """Get or create the scheduler service singleton.

    .. deprecated::
        Use gRPC engine instead: get_scheduler_proxy() from client.engine_proxy
    """
    import warnings
    warnings.warn(
        "get_scheduler_service() is deprecated. "
        "Use get_scheduler_proxy() from gaius.client.engine_proxy instead. "
        "The client-side scheduler bypasses gRPC and uses hardcoded model names.",
        DeprecationWarning,
        stacklevel=2,
    )
    global _service
    if _service is None:
        _service = SchedulerService()
    return _service


# Convenience alias
get_service = get_scheduler_service
