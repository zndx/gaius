"""Scheduler service for inference job routing.

Routes inference requests to backends with priority queue,
metrics tracking, and budget management.

BDD Alignment (swarm_evolution.feature):
- Swarm results include token metrics → MetricsTracker
- XAI budget management → XAIBudget class
- Tiered evaluation respects budget → tiered_evaluate
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, date
from enum import Enum
from typing import Any, Callable, Optional
from collections import deque

from ..backends import (
    BackendRouter,
    InferenceRequest,
    InferenceResponse,
    OptillmTechnique,
)
from ..config import EngineConfig

logger = logging.getLogger(__name__)


class JobPriority(Enum):
    """Job priority levels."""

    CRITICAL = 4  # Evolution evaluation, user-facing
    HIGH = 3  # Swarm synthesis
    NORMAL = 2  # Regular inference
    LOW = 1  # Background tasks
    BATCH = 0  # Bulk processing


@dataclass
class InferenceJob:
    """Inference job in the queue.

    Attributes:
        id: Unique job identifier
        request: The inference request
        priority: Job priority
        submitted_at: When job was submitted
        started_at: When processing started
        completed_at: When job completed
        result: Response when complete
        callback: Optional completion callback
    """

    id: str
    request: InferenceRequest
    priority: JobPriority = JobPriority.NORMAL
    submitted_at: datetime = field(default_factory=datetime.now)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    result: Optional[InferenceResponse] = None
    callback: Optional[Callable] = None

    @property
    def wait_time_ms(self) -> int:
        """Time spent waiting in queue."""
        if self.started_at:
            return int((self.started_at - self.submitted_at).total_seconds() * 1000)
        return int((datetime.now() - self.submitted_at).total_seconds() * 1000)

    @property
    def processing_time_ms(self) -> int:
        """Time spent processing."""
        if not self.started_at:
            return 0
        end = self.completed_at or datetime.now()
        return int((end - self.started_at).total_seconds() * 1000)


@dataclass
class AgentMetrics:
    """Metrics for an agent.

    BDD: "Swarm results include token metrics"
    - Total tokens used
    - Latency metrics
    - Per-agent contributions
    """

    agent_alias: str
    total_requests: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_latency_ms: int = 0
    error_count: int = 0

    # Recent latencies for p50/p99 calculation
    recent_latencies: deque = field(default_factory=lambda: deque(maxlen=100))

    @property
    def avg_latency_ms(self) -> float:
        """Average latency in milliseconds."""
        if self.total_requests == 0:
            return 0.0
        return self.total_latency_ms / self.total_requests

    @property
    def avg_tokens_per_request(self) -> float:
        """Average total tokens per request."""
        if self.total_requests == 0:
            return 0.0
        return (self.total_input_tokens + self.total_output_tokens) / self.total_requests

    @property
    def p50_latency_ms(self) -> int:
        """50th percentile latency."""
        if not self.recent_latencies:
            return 0
        sorted_latencies = sorted(self.recent_latencies)
        idx = len(sorted_latencies) // 2
        return sorted_latencies[idx]

    @property
    def p99_latency_ms(self) -> int:
        """99th percentile latency."""
        if not self.recent_latencies:
            return 0
        sorted_latencies = sorted(self.recent_latencies)
        idx = int(len(sorted_latencies) * 0.99)
        return sorted_latencies[min(idx, len(sorted_latencies) - 1)]

    def record(self, response: InferenceResponse) -> None:
        """Record a response for metrics."""
        self.total_requests += 1
        self.total_input_tokens += response.input_tokens
        self.total_output_tokens += response.output_tokens
        self.total_latency_ms += response.latency_ms
        self.recent_latencies.append(response.latency_ms)

        if response.error:
            self.error_count += 1

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for serialization."""
        return {
            "agent_alias": self.agent_alias,
            "total_requests": self.total_requests,
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "total_latency_ms": self.total_latency_ms,
            "avg_latency_ms": self.avg_latency_ms,
            "p50_latency_ms": self.p50_latency_ms,
            "p99_latency_ms": self.p99_latency_ms,
            "error_count": self.error_count,
            "error_rate": self.error_count / max(1, self.total_requests),
        }


@dataclass
class XAIBudget:
    """XAI API budget tracking.

    BDD: "XAI budget management"
    - Daily Used / Daily Limit
    - Weekly Used / Weekly Limit
    - Tiered evaluation respects budget
    """

    daily_limit: int = 50
    weekly_limit: int = 200

    # Current usage
    daily_used: int = 0
    weekly_used: int = 0

    # Tracking dates
    current_day: date = field(default_factory=date.today)
    week_start: date = field(default_factory=lambda: date.today())

    def _maybe_reset(self) -> None:
        """Reset counters if day/week changed."""
        today = date.today()

        # Reset daily counter
        if today != self.current_day:
            self.daily_used = 0
            self.current_day = today

        # Reset weekly counter (Monday is 0)
        if today.weekday() == 0 and today != self.week_start:
            self.weekly_used = 0
            self.week_start = today

    def can_use(self) -> bool:
        """Check if XAI can be used within budget."""
        self._maybe_reset()
        return self.daily_used < self.daily_limit and self.weekly_used < self.weekly_limit

    def record_use(self) -> None:
        """Record XAI API usage."""
        self._maybe_reset()
        self.daily_used += 1
        self.weekly_used += 1

    @property
    def daily_remaining(self) -> int:
        """Remaining daily budget."""
        self._maybe_reset()
        return max(0, self.daily_limit - self.daily_used)

    @property
    def weekly_remaining(self) -> int:
        """Remaining weekly budget."""
        self._maybe_reset()
        return max(0, self.weekly_limit - self.weekly_used)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for status display."""
        self._maybe_reset()
        return {
            "daily_used": self.daily_used,
            "daily_limit": self.daily_limit,
            "daily_remaining": self.daily_remaining,
            "weekly_used": self.weekly_used,
            "weekly_limit": self.weekly_limit,
            "weekly_remaining": self.weekly_remaining,
        }


class SchedulerService:
    """Inference scheduler with priority queue and metrics.

    Routes inference requests to appropriate backends with
    tracking for token usage, latency, and budget management.

    BDD Scenarios Supported:
    - Swarm results include token metrics (AgentMetrics)
    - XAI budget with '/evolve budget' (XAIBudget)
    - Tiered evaluation respects budget (tiered_evaluate)
    """

    def __init__(
        self,
        config: EngineConfig,
        backend_router: BackendRouter,
    ):
        """Initialize scheduler service.

        Args:
            config: Engine configuration
            backend_router: Backend router for inference
        """
        self.config = config
        self.backend_router = backend_router

        # Job queue (priority sorted)
        self._queue: list[InferenceJob] = []
        self._queue_lock = asyncio.Lock()

        # Per-agent metrics
        self._metrics: dict[str, AgentMetrics] = {}

        # XAI budget tracking
        self._xai_budget = XAIBudget()

        # Job tracking
        self._job_counter = 0
        self._completed_jobs: deque[InferenceJob] = deque(maxlen=1000)

        # Processing state
        self._running = False
        self._worker_task: Optional[asyncio.Task] = None

        logger.info("SchedulerService initialized")

    async def start(self) -> None:
        """Start the scheduler service."""
        if self._running:
            return

        self._running = True
        self._worker_task = asyncio.create_task(self._process_queue())

        logger.info("SchedulerService started")

    async def stop(self) -> None:
        """Stop the scheduler service."""
        if not self._running:
            return

        self._running = False

        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass

        logger.info("SchedulerService stopped")

    # ─────────────────────────────────────────────────────────────────────────
    # Job Submission
    # ─────────────────────────────────────────────────────────────────────────

    async def submit(
        self,
        request: InferenceRequest,
        priority: JobPriority = JobPriority.NORMAL,
    ) -> InferenceResponse:
        """Submit a job and wait for completion.

        Args:
            request: Inference request
            priority: Job priority

        Returns:
            InferenceResponse when complete
        """
        job = await self._enqueue(request, priority)

        # Wait for completion
        while job.result is None:
            await asyncio.sleep(0.01)

        return job.result

    async def submit_async(
        self,
        request: InferenceRequest,
        priority: JobPriority = JobPriority.NORMAL,
        callback: Optional[Callable] = None,
    ) -> str:
        """Submit a job without waiting.

        Args:
            request: Inference request
            priority: Job priority
            callback: Optional callback when complete

        Returns:
            Job ID for tracking
        """
        job = await self._enqueue(request, priority, callback)
        return job.id

    async def _enqueue(
        self,
        request: InferenceRequest,
        priority: JobPriority,
        callback: Optional[Callable] = None,
    ) -> InferenceJob:
        """Add job to queue."""
        async with self._queue_lock:
            self._job_counter += 1
            job = InferenceJob(
                id=f"job-{self._job_counter}",
                request=request,
                priority=priority,
                callback=callback,
            )

            # Insert in priority order
            inserted = False
            for i, existing in enumerate(self._queue):
                if job.priority.value > existing.priority.value:
                    self._queue.insert(i, job)
                    inserted = True
                    break

            if not inserted:
                self._queue.append(job)

            return job

    async def _process_queue(self) -> None:
        """Background queue processor.

        Waits for backends to be ready before processing jobs.
        This implements the command queue pattern where inference
        requests are held until initialization completes.
        """
        # Wait for at least one backend to be ready
        await self._wait_for_backends()

        while self._running:
            job = None

            async with self._queue_lock:
                if self._queue:
                    job = self._queue.pop(0)

            if job:
                await self._process_job(job)
            else:
                await asyncio.sleep(0.01)

    async def _wait_for_backends(self, timeout: float = 300.0) -> None:
        """Wait for at least one backend to be ready.

        Args:
            timeout: Maximum time to wait in seconds (default 5 minutes)

        During engine initialization (~240s), this holds inference
        requests until endpoints are available. Uses exponential
        backoff to avoid hammering health checks.
        """
        start = asyncio.get_event_loop().time()
        wait_time = 1.0  # Start with 1s, increase exponentially

        while self._running:
            elapsed = asyncio.get_event_loop().time() - start
            if elapsed > timeout:
                logger.warning("Backend wait timeout - proceeding anyway")
                return

            # Check if any backends are available
            if await self._any_backend_ready():
                logger.info(f"Backends ready after {elapsed:.1f}s")
                return

            logger.debug(f"Waiting for backends... ({elapsed:.0f}s elapsed)")
            await asyncio.sleep(wait_time)
            wait_time = min(wait_time * 1.5, 10.0)  # Cap at 10s

    async def _any_backend_ready(self) -> bool:
        """Check if any inference backend is ready.

        Returns:
            True if at least one backend can accept requests
        """
        try:
            # Get backend status (sync method, wrap for async context)
            status = self.backend_router.get_status()

            # Check vLLM endpoints
            vllm_status = status.get("vllm", {})
            vllm_running = vllm_status.get("total_running", 0)

            # Check optillm
            optillm_status = status.get("optillm", {})
            optillm_healthy = optillm_status.get("healthy", False)

            return vllm_running > 0 or optillm_healthy
        except Exception as e:
            logger.debug(f"Backend status check failed: {e}")
            return False

    async def _process_job(self, job: InferenceJob) -> None:
        """Process a single job."""
        job.started_at = datetime.now()

        try:
            response = await self.backend_router.route(job.request)
            job.result = response
            job.completed_at = datetime.now()

            # Record metrics
            self._record_metrics(job.request.agent_alias, response)

            # Store completed job
            self._completed_jobs.append(job)

            # Call callback if provided
            if job.callback:
                try:
                    job.callback(response)
                except Exception as e:
                    logger.error(f"Job callback error: {e}")

        except Exception as e:
            logger.error(f"Job processing error: {e}")
            job.result = InferenceResponse(
                content="",
                model="",
                backend="",
                error=str(e),
            )
            job.completed_at = datetime.now()

    def _record_metrics(self, agent_alias: str, response: InferenceResponse) -> None:
        """Record metrics for a response."""
        if agent_alias not in self._metrics:
            self._metrics[agent_alias] = AgentMetrics(agent_alias=agent_alias)

        self._metrics[agent_alias].record(response)

    # ─────────────────────────────────────────────────────────────────────────
    # Direct Completion (Synchronous-style API)
    # ─────────────────────────────────────────────────────────────────────────

    async def complete(
        self,
        prompt: str,
        agent_alias: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        technique: Optional[str] = None,
        priority: JobPriority = JobPriority.NORMAL,
    ) -> InferenceResponse:
        """Complete a prompt through the scheduler.

        Args:
            prompt: User prompt
            agent_alias: Agent to use
            system_prompt: Optional system prompt
            temperature: Sampling temperature
            max_tokens: Maximum tokens
            technique: Optional optillm technique
            priority: Job priority

        Returns:
            InferenceResponse
        """
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        request = InferenceRequest(
            messages=messages,
            agent_alias=agent_alias,
            temperature=temperature,
            max_tokens=max_tokens,
            technique=technique,
        )

        return await self.submit(request, priority)

    # ─────────────────────────────────────────────────────────────────────────
    # Tiered Evaluation (BDD: XAI budget management)
    # ─────────────────────────────────────────────────────────────────────────

    async def tiered_evaluate(
        self,
        prompt: str,
        force_xai: bool = False,
    ) -> InferenceResponse:
        """Evaluate using tiered strategy.

        BDD: "Tiered evaluation respects budget"
        - Uses local model by default
        - XAI only if budget allows and force_xai=True

        Args:
            prompt: Prompt to evaluate
            force_xai: Force XAI if budget allows

        Returns:
            InferenceResponse from appropriate backend
        """
        # Check if XAI can be used
        use_xai = force_xai and self._xai_budget.can_use()

        if use_xai:
            # Use XAI (via a special "xai" agent if configured)
            # For now, we record the usage but route through normal path
            self._xai_budget.record_use()
            logger.info("Using XAI for evaluation (budget-permitting)")

            # Route to a frontier-capable agent
            return await self.complete(
                prompt=prompt,
                agent_alias="reasoning",  # Use best local model
                priority=JobPriority.CRITICAL,
            )
        else:
            # Use local model
            logger.debug("Using local model for evaluation")
            return await self.complete(
                prompt=prompt,
                agent_alias="instruct",  # Use instruct local model
                priority=JobPriority.HIGH,
            )

    # ─────────────────────────────────────────────────────────────────────────
    # Metrics (BDD: Token metrics)
    # ─────────────────────────────────────────────────────────────────────────

    def get_agent_metrics(self, agent_alias: str) -> Optional[AgentMetrics]:
        """Get metrics for an agent."""
        return self._metrics.get(agent_alias)

    def get_all_metrics(self) -> dict[str, dict[str, Any]]:
        """Get metrics for all agents.

        BDD: "Swarm results include token metrics"
        - Total tokens used
        - Latency metrics
        - Per-agent contributions

        Returns:
            Dict mapping agent alias to metrics
        """
        return {alias: m.to_dict() for alias, m in self._metrics.items()}

    def get_total_metrics(self) -> dict[str, Any]:
        """Get aggregate metrics across all agents."""
        total_requests = sum(m.total_requests for m in self._metrics.values())
        total_input = sum(m.total_input_tokens for m in self._metrics.values())
        total_output = sum(m.total_output_tokens for m in self._metrics.values())
        total_latency = sum(m.total_latency_ms for m in self._metrics.values())
        total_errors = sum(m.error_count for m in self._metrics.values())

        return {
            "total_requests": total_requests,
            "total_input_tokens": total_input,
            "total_output_tokens": total_output,
            "total_tokens": total_input + total_output,
            "total_latency_ms": total_latency,
            "avg_latency_ms": total_latency / max(1, total_requests),
            "total_errors": total_errors,
            "error_rate": total_errors / max(1, total_requests),
        }

    def reset_metrics(self) -> None:
        """Reset all metrics."""
        self._metrics.clear()

    # ─────────────────────────────────────────────────────────────────────────
    # XAI Budget (BDD: '/evolve budget')
    # ─────────────────────────────────────────────────────────────────────────

    def get_xai_budget(self) -> dict[str, Any]:
        """Get XAI budget status.

        BDD: "View XAI budget with '/evolve budget'"

        Returns:
            Budget status dict
        """
        return self._xai_budget.to_dict()

    def reset_xai_budget(
        self, reset_daily: bool = True, reset_weekly: bool = False
    ) -> None:
        """Reset XAI budget counters."""
        if reset_daily:
            self._xai_budget.daily_used = 0
        if reset_weekly:
            self._xai_budget.weekly_used = 0

    # ─────────────────────────────────────────────────────────────────────────
    # Swarm Analysis
    # ─────────────────────────────────────────────────────────────────────────

    async def run_swarm(
        self,
        domain: str,
        context: str = "",
        roles: list[str] | None = None,
    ) -> dict[str, dict[str, Any]]:
        """Run multi-agent swarm analysis.

        Routes each agent role to the appropriate endpoint via agents.conf,
        NOT hardcoded model names.

        Args:
            domain: Domain to analyze (e.g., "pension", "kudu")
            context: Additional context
            roles: Agent roles to include (default: all core roles)

        Returns:
            Dict mapping role name to result dict with:
            - status: "completed" or "failed"
            - content: Response content
            - model: Actual model used
            - latency_ms: Response time
            - input_tokens: Tokens in
            - output_tokens: Tokens out
            - error: Error message if failed
        """
        import asyncio
        from gaius.agents.roles import AgentRole, get_role

        # Map role capabilities to endpoints
        CAPABILITY_TO_ENDPOINT = {
            "reasoning": "reasoning",      # Strong reasoning models
            "long_context": "reasoning",   # Same - needs context
            "coding": "instruct",          # Code generation via instruct
            "adversarial": "reasoning",    # Needs reasoning
            "synthesis": "instruct",       # Synthesis via instruct
        }

        # Default to core swarm roles
        if roles is None:
            roles = ["Leader", "Risk", "Optimizer", "Planner", "Critic", "Executor", "Adversary"]

        # Create tasks for each role
        async def run_agent(role_name: str) -> tuple[str, dict[str, Any]]:
            try:
                role_enum = AgentRole(role_name)
                role_def = get_role(role_enum)
            except (ValueError, KeyError):
                return role_name, {
                    "status": "failed",
                    "error": f"Unknown role: {role_name}",
                }

            # Determine endpoint from capabilities
            endpoint = "instruct"  # Default
            for cap in role_def.model_capabilities:
                if cap in CAPABILITY_TO_ENDPOINT:
                    endpoint = CAPABILITY_TO_ENDPOINT[cap]
                    break

            # Generate prompt
            prompt = role_def.get_prompt(domain, context)

            try:
                # Call through scheduler (uses agents.conf for model resolution)
                response = await self.complete(
                    prompt=prompt,
                    agent_alias=endpoint,
                    temperature=role_def.temperature,
                    max_tokens=role_def.max_tokens,
                    priority=JobPriority.HIGH,
                )

                return role_name, {
                    "status": "completed" if not response.error else "failed",
                    "content": response.content,
                    "model": response.model,
                    "endpoint": endpoint,
                    "latency_ms": response.latency_ms,
                    "input_tokens": response.input_tokens,
                    "output_tokens": response.output_tokens,
                    "error": response.error,
                }
            except Exception as e:
                return role_name, {
                    "status": "failed",
                    "content": "",
                    "endpoint": endpoint,
                    "error": str(e),
                }

        # Run all agents concurrently
        tasks = [run_agent(role) for role in roles]
        results_list = await asyncio.gather(*tasks)

        # Convert to dict
        return {name: result for name, result in results_list}

    async def run_swarm_clt(
        self,
        domain: str,
        context: str = "",
        roles: list[str] | None = None,
    ) -> dict[str, dict[str, Any]]:
        """Run CLT-enhanced swarm analysis.

        DEPRECATED: This method bypasses the Yunikorn-style workload system.
        Use gRPC SwarmStream with clt=True instead, which properly allocates
        GPU resources via the orchestrator's begin_workload/complete_workload.

        Raises:
            RuntimeError: Always fails with guidance to use proper CLT path
        """
        raise RuntimeError(
            "run_swarm_clt() is deprecated. CLT requires GPU allocation via workload system.\n"
            "  Use: gRPC SwarmStream with clt=True\n"
            "  Or:  CLI '/swarm clt <domain>'\n"
            "  Guru Meditation: #CLT.00000002.DEPRECATED\n"
            "  The workload system handles GPU allocation, eviction, and restoration."
        )

    # ─────────────────────────────────────────────────────────────────────────
    # Status
    # ─────────────────────────────────────────────────────────────────────────

    def get_status(self) -> dict[str, Any]:
        """Get scheduler status."""
        return {
            "running": self._running,
            "queue_depth": len(self._queue),
            "total_jobs_completed": len(self._completed_jobs),
            "xai_budget": self.get_xai_budget(),
            "metrics": self.get_total_metrics(),
            "per_agent_metrics": self.get_all_metrics(),
        }

    def get_job_status(self, job_id: str) -> Optional[dict[str, Any]]:
        """Get status of a specific job."""
        # Check queue
        for job in self._queue:
            if job.id == job_id:
                return {
                    "id": job.id,
                    "status": "queued",
                    "wait_time_ms": job.wait_time_ms,
                    "priority": job.priority.value,
                }

        # Check completed
        for job in self._completed_jobs:
            if job.id == job_id:
                return {
                    "id": job.id,
                    "status": "completed" if job.result and not job.result.error else "failed",
                    "wait_time_ms": job.wait_time_ms,
                    "processing_time_ms": job.processing_time_ms,
                    "error": job.result.error if job.result else None,
                }

        return None
