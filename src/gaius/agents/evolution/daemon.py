"""Background evolution daemon for Agent0-style self-improvement.

Monitors GPU utilization and runs agent optimization cycles
when resources are idle. Preempts for interactive requests.

Usage:
    daemon = get_evolution_daemon()
    await daemon.start()

    # Runs in background, checking GPU every poll_interval seconds
    # When idle: runs optimization cycle for next agent in rotation

    await daemon.stop()  # Graceful shutdown
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Awaitable

from .preemption import PreemptedError, get_preemption_manager

logger = logging.getLogger(__name__)


@dataclass
class EvolutionConfig:
    """Configuration for evolution daemon."""

    # Enable/disable daemon
    enabled: bool = True

    # GPU utilization threshold to consider idle (percent)
    idle_threshold: float = 20.0

    # Minimum idle duration before starting (seconds)
    min_idle_duration: float = 30.0

    # How often to check GPU idle status (seconds)
    poll_interval: float = 5.0

    # Number of candidates to evaluate per cycle
    candidates_per_cycle: int = 3

    # Maximum cycles per hour (rate limiting)
    max_cycles_per_hour: int = 10

    # Minimum training examples required
    min_examples: int = 5

    # Optimization strategy: apo, gepa, or hybrid
    strategy: str = "gepa"

    # Minimum improvement threshold to save new version (percent)
    min_improvement: float = 5.0

    # Agents to optimize (in rotation)
    # NOTE: Must match agents with active versions in agent_versions table
    agents: list[str] = field(default_factory=lambda: [
        "leader", "risk", "critic", "opportunity", "domain"
    ])

    # Parallel mode: use 6 vLLM instances for faster evolution
    parallel: bool = False

    # Endpoint names for parallel mode
    parallel_endpoints: list[str] = field(default_factory=lambda: [
        "evo0", "evo1", "evo2", "evo3", "evo4", "evo5"
    ])

    # Task ideation settings
    task_ideation_enabled: bool = True

    # Run ideation every N evolution cycles (e.g., every 5th cycle)
    ideation_cycle_interval: int = 5

    # Maximum task concepts to generate per ideation cycle
    max_ideation_concepts: int = 2

    # Minimum novelty score for task concepts
    min_novelty_threshold: float = 0.5

    # Model merging settings
    merge_enabled: bool = True

    # Run merge every N evolution cycles (e.g., every 10th cycle)
    merge_cycle_interval: int = 10

    # Minimum version score to consider for merging
    merge_min_score: float = 0.7

    # Minimum improvement threshold for merged models (percent)
    merge_min_improvement: float = 2.0

    # RASE Intrinsic Verification Settings
    # Use RASE objectives for intrinsic verification (no external models)
    use_intrinsic_verification: bool = True

    # KB root for objective loading
    kb_root: str = "build/dev"

    # Run calibration every N evolution cycles
    calibration_cycle_interval: int = 20

    # Prefer Cerebras over XAI for calibration
    prefer_cerebras: bool = True

    # Capture evidence to HX Iceberg tables
    capture_evidence: bool = True


@dataclass
class EvolutionCycleResult:
    """Result from a single evolution cycle."""

    agent_id: str
    success: bool
    improvement_percent: float = 0.0
    new_version_id: str | None = None
    baseline_score: float = 0.0
    best_score: float = 0.0
    examples_used: int = 0
    candidates_evaluated: int = 0
    preempted: bool = False
    error: str | None = None
    duration_ms: int = 0


class EvolutionDaemon:
    """Background daemon for autonomous agent improvement.

    Implements Agent0-style self-evolution:
    - Monitors GPU utilization via health module
    - Runs optimization cycles when GPUs are idle
    - Preempts immediately for interactive requests
    - Rotates through configured agents

    The daemon uses existing APO/GEPA optimization infrastructure
    with training examples collected from successful interactions.
    """

    def __init__(self, config: EvolutionConfig | None = None):
        """Initialize evolution daemon.

        Args:
            config: Evolution configuration (uses defaults if None)
        """
        self.config = config or EvolutionConfig()

        # State
        self._running = False
        self._task: asyncio.Task | None = None
        self._preemption_manager = get_preemption_manager()
        self._parallel_client = None  # Lazy-loaded when parallel=True

        # Metrics
        self._cycles_completed = 0
        self._total_improvement = 0.0
        self._last_cycle_at: datetime | None = None
        self._agent_index = 0  # Current position in rotation

        # Task ideation state
        self._ideation_agent = None  # Lazy-loaded
        self._ideation_cycles_completed = 0
        self._last_ideation_at: datetime | None = None
        self._drafts_created = 0

        # Model merge state
        self._merge_coordinator = None  # Lazy-loaded
        self._merge_cycles_completed = 0
        self._last_merge_at: datetime | None = None
        self._models_merged = 0

        # RASE intrinsic verification state
        self._daemon_oracle = None  # Lazy-loaded
        self._objective_generator = None  # Lazy-loaded
        self._calibration_oracle = None  # Lazy-loaded
        self._calibration_cycles_completed = 0
        self._last_calibration_at: datetime | None = None

        # Callbacks
        self._on_cycle_complete: list[Callable[[EvolutionCycleResult], Awaitable[None]]] = []

    @property
    def running(self) -> bool:
        """Check if daemon is running."""
        return self._running

    @property
    def cycles_completed(self) -> int:
        """Total evolution cycles completed."""
        return self._cycles_completed

    @property
    def total_improvement(self) -> float:
        """Total improvement percentage across all cycles."""
        return self._total_improvement

    @property
    def next_agent(self) -> str:
        """Next agent in rotation."""
        if not self.config.agents:
            return ""
        return self.config.agents[self._agent_index % len(self.config.agents)]

    @property
    def daemon_oracle(self):
        """Get daemon oracle for intrinsic verification (lazy-loaded)."""
        if self._daemon_oracle is None and self.config.use_intrinsic_verification:
            from .daemon_oracle import DaemonOracle
            self._daemon_oracle = DaemonOracle(
                kb_root=self.config.kb_root,
                capture_evidence=self.config.capture_evidence,
            )
        return self._daemon_oracle

    @property
    def objective_generator(self):
        """Get objective generator for task creation (lazy-loaded)."""
        if self._objective_generator is None and self.config.use_intrinsic_verification:
            from .objective_generator import ObjectiveTaskGenerator
            self._objective_generator = ObjectiveTaskGenerator(
                kb_root=self.config.kb_root,
            )
        return self._objective_generator

    @property
    def calibration_oracle(self):
        """Get calibration oracle for outer loop (lazy-loaded)."""
        if self._calibration_oracle is None:
            from .calibration import CalibrationOracle, CalibrationConfig
            self._calibration_oracle = CalibrationOracle(
                CalibrationConfig(
                    prefer_cerebras=self.config.prefer_cerebras,
                )
            )
        return self._calibration_oracle

    async def start(self, parallel: bool | None = None) -> None:
        """Start the evolution daemon.

        Begins background monitoring of GPU utilization
        and runs optimization cycles when idle.

        Args:
            parallel: Override config.parallel if specified.
                      If True, starts 6 parallel vLLM endpoints.
        """
        if self._running:
            logger.warning("Evolution daemon already running")
            return

        if not self.config.enabled:
            logger.info("Evolution daemon disabled by config")
            return

        # Override parallel setting if specified
        if parallel is not None:
            self.config.parallel = parallel

        # Start parallel endpoints if enabled
        if self.config.parallel:
            await self._start_parallel_endpoints()

        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info(
            f"Evolution daemon started (parallel={self.config.parallel}, "
            f"endpoints={len(self.config.parallel_endpoints) if self.config.parallel else 1})"
        )

    async def _start_parallel_endpoints(self) -> dict[str, bool]:
        """Start all parallel vLLM endpoints for evolution.

        Returns:
            Dict of endpoint name -> success status
        """
        from ...inference.parallel import get_parallel_client

        client = get_parallel_client()
        self._parallel_client = client

        logger.info(f"Starting {len(self.config.parallel_endpoints)} parallel endpoints...")
        results = await client.start(self.config.parallel_endpoints)

        successful = sum(1 for v in results.values() if v)
        logger.info(f"Started {successful}/{len(self.config.parallel_endpoints)} endpoints")

        return results

    async def stop(self) -> None:
        """Stop the evolution daemon gracefully.

        Waits for current cycle to complete or preempt.
        """
        if not self._running:
            return

        self._running = False

        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

        # Stop parallel endpoints if they were started
        if self._parallel_client is not None:
            logger.info("Stopping parallel endpoints...")
            await self._parallel_client.stop()
            self._parallel_client = None

        logger.info("Evolution daemon stopped")

    async def force_evolution_cycle(
        self,
        agent_id: str | None = None,
    ) -> EvolutionCycleResult:
        """Force an immediate evolution cycle.

        Bypasses idle check and rate limiting.

        Args:
            agent_id: Specific agent to optimize (None = next in rotation)

        Returns:
            EvolutionCycleResult with optimization outcome
        """
        target_agent = agent_id or self.next_agent

        if not target_agent:
            return EvolutionCycleResult(
                agent_id="",
                success=False,
                error="No agents configured",
            )

        logger.info(f"Forcing evolution cycle for {target_agent}")
        return await self._run_evolution_cycle(target_agent)

    def on_cycle_complete(
        self,
        callback: Callable[[EvolutionCycleResult], Awaitable[None]],
    ) -> None:
        """Register callback for cycle completion.

        Args:
            callback: Async function called after each cycle
        """
        self._on_cycle_complete.append(callback)

    def get_status(self) -> dict:
        """Get daemon status for monitoring.

        Returns:
            Status dict with running state, metrics, etc.
        """
        # Get parallel endpoint count if active
        parallel_endpoints = 0
        if self._parallel_client is not None:
            parallel_endpoints = self._parallel_client.num_endpoints

        return {
            "running": self._running,
            "enabled": self.config.enabled,
            "cycles_completed": self._cycles_completed,
            "total_improvement_percent": round(self._total_improvement, 2),
            "last_cycle_at": self._last_cycle_at.isoformat() if self._last_cycle_at else None,
            "next_agent": self.next_agent,
            "parallel": self.config.parallel,
            "parallel_endpoints": parallel_endpoints,
            # Task ideation metrics
            "ideation": {
                "enabled": self.config.task_ideation_enabled,
                "cycles_completed": self._ideation_cycles_completed,
                "drafts_created": self._drafts_created,
                "last_ideation_at": (
                    self._last_ideation_at.isoformat()
                    if self._last_ideation_at else None
                ),
                "next_ideation_in": (
                    self.config.ideation_cycle_interval -
                    (self._cycles_completed % self.config.ideation_cycle_interval)
                ) if self.config.task_ideation_enabled else None,
            },
            # Model merging metrics
            "merging": {
                "enabled": self.config.merge_enabled,
                "cycles_completed": self._merge_cycles_completed,
                "models_merged": self._models_merged,
                "last_merge_at": (
                    self._last_merge_at.isoformat()
                    if self._last_merge_at else None
                ),
                "next_merge_in": (
                    self.config.merge_cycle_interval -
                    (self._cycles_completed % self.config.merge_cycle_interval)
                ) if self.config.merge_enabled else None,
            },
            # RASE intrinsic verification metrics
            "intrinsic_verification": {
                "enabled": self.config.use_intrinsic_verification,
                "kb_root": self.config.kb_root,
                "capture_evidence": self.config.capture_evidence,
                "calibration_cycles_completed": self._calibration_cycles_completed,
                "last_calibration_at": (
                    self._last_calibration_at.isoformat()
                    if self._last_calibration_at else None
                ),
                "next_calibration_in": (
                    self.config.calibration_cycle_interval -
                    (self._cycles_completed % self.config.calibration_cycle_interval)
                ) if self.config.use_intrinsic_verification else None,
                "prefer_cerebras": self.config.prefer_cerebras,
            },
            "config": {
                "idle_threshold": self.config.idle_threshold,
                "poll_interval": self.config.poll_interval,
                "max_cycles_per_hour": self.config.max_cycles_per_hour,
                "strategy": self.config.strategy,
                "agents": self.config.agents,
            },
        }

    async def _run_loop(self) -> None:
        """Main daemon loop."""
        idle_start: datetime | None = None

        while self._running:
            try:
                # Check rate limiting
                if self._is_rate_limited():
                    await asyncio.sleep(self.config.poll_interval)
                    continue

                # Check GPU idle status
                is_idle = await self._gpus_are_idle()

                if is_idle:
                    if idle_start is None:
                        idle_start = datetime.now()
                        logger.debug("GPUs became idle")

                    # Check if idle long enough
                    idle_duration = (datetime.now() - idle_start).total_seconds()
                    if idle_duration >= self.config.min_idle_duration:
                        # Run evolution cycle
                        try:
                            result = await self._run_evolution_cycle(self.next_agent)
                            await self._notify_cycle_complete(result)

                            # Advance rotation
                            self._agent_index = (self._agent_index + 1) % len(self.config.agents)

                            # Check if it's time for task ideation
                            if (
                                self.config.task_ideation_enabled and
                                self._cycles_completed > 0 and
                                self._cycles_completed % self.config.ideation_cycle_interval == 0
                            ):
                                await self._run_ideation_cycle()

                            # Check if it's time for model merging
                            if (
                                self.config.merge_enabled and
                                self._cycles_completed > 0 and
                                self._cycles_completed % self.config.merge_cycle_interval == 0
                            ):
                                await self._run_merge_cycle()

                            # Check if it's time for calibration (outer loop)
                            if (
                                self.config.use_intrinsic_verification and
                                self._cycles_completed > 0 and
                                self._cycles_completed % self.config.calibration_cycle_interval == 0
                            ):
                                await self._run_calibration_cycle()

                        except PreemptedError as e:
                            logger.info(f"Evolution preempted: {e.reason}")
                            result = EvolutionCycleResult(
                                agent_id=self.next_agent,
                                success=False,
                                preempted=True,
                            )
                            await self._notify_cycle_complete(result)

                        # Reset idle timer after cycle
                        idle_start = None
                else:
                    # Reset idle timer
                    idle_start = None

                await asyncio.sleep(self.config.poll_interval)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Evolution loop error: {e}")
                await asyncio.sleep(30)  # Back off on errors

    async def _gpus_are_idle(self) -> bool:
        """Check if GPUs are idle enough for evolution.

        Returns:
            True if all GPUs below threshold and no pending jobs
        """
        try:
            # Try to use health monitor
            from ...inference.health import get_health_monitor

            monitor = get_health_monitor()
            gpu_status = monitor.get_all_gpu_health()

            for gpu in gpu_status:
                if gpu.gpu_utilization_percent > self.config.idle_threshold:
                    return False

            # Also check scheduler queue via gRPC
            try:
                from ...client.engine_proxy import get_scheduler_proxy, use_engine_proxy

                if use_engine_proxy():
                    import asyncio
                    scheduler = asyncio.get_event_loop().run_until_complete(
                        get_scheduler_proxy()
                    )
                    status = scheduler.get_status()
                    if status.get("pending_jobs", 0) > 0:
                        return False
            except Exception:
                pass  # Scheduler not available

            return True

        except ImportError:
            # Health monitor not available - assume idle
            logger.debug("Health monitor not available, assuming idle")
            return True
        except Exception as e:
            logger.debug(f"GPU idle check failed: {e}")
            return False

    def _is_rate_limited(self) -> bool:
        """Check if we've hit the rate limit.

        Returns:
            True if should wait before next cycle
        """
        if self._last_cycle_at is None:
            return False

        # Compute minimum interval between cycles
        min_interval = 3600 / self.config.max_cycles_per_hour
        elapsed = (datetime.now() - self._last_cycle_at).total_seconds()

        return elapsed < min_interval

    async def _run_evolution_cycle(self, agent_id: str) -> EvolutionCycleResult:
        """Run one evolution cycle for an agent.

        Delegates to EvolutionEngine for actual execution. The engine
        handles all inference via AgentRunner, ensuring proper GPU
        management and output validation.

        Args:
            agent_id: Agent to optimize

        Returns:
            EvolutionCycleResult with outcome
        """
        start_time = datetime.now()

        try:
            # Use EvolutionEngine for the actual cycle
            from .engine import get_engine

            engine = await get_engine()

            # Run with preemption support
            async def run_cycle():
                return await engine.run_evolution_cycle(
                    agent_id=agent_id,
                    num_items=10,  # Use reasonable sample size
                )

            cycle_result = await self._preemption_manager.run_with_preemption(
                run_cycle(),
                timeout=300,
            )

            duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)

            # Convert engine CycleResult to daemon EvolutionCycleResult
            result = EvolutionCycleResult(
                agent_id=agent_id,
                success=cycle_result.success,
                improvement_percent=cycle_result.improvement_percent,
                new_version_id=cycle_result.new_version_id,
                baseline_score=cycle_result.baseline_score,
                best_score=cycle_result.best_score,
                examples_used=cycle_result.trajectories_run,
                candidates_evaluated=cycle_result.trajectories_succeeded,
                duration_ms=duration_ms,
                error=cycle_result.error,
            )

            if result.success and result.improvement_percent >= self.config.min_improvement:
                self._cycles_completed += 1
                self._total_improvement += result.improvement_percent
                self._last_cycle_at = datetime.now()

                logger.info(
                    f"Evolution improved {agent_id}: "
                    f"{result.improvement_percent:.1f}% "
                    f"(version: {result.new_version_id})"
                )
            else:
                logger.info(
                    f"Evolution cycle for {agent_id}: "
                    f"{'no improvement' if result.success else 'failed'} "
                    f"({result.improvement_percent:.1f}%)"
                )

            # Log to database for tracking
            await self._log_cycle_to_db(result, trigger_type="idle")

            return result

        except PreemptedError:
            raise  # Re-raise for loop to handle
        except Exception as e:
            duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)
            logger.error(f"Evolution cycle failed for {agent_id}: {e}")
            return EvolutionCycleResult(
                agent_id=agent_id,
                success=False,
                error=str(e),
                duration_ms=duration_ms,
            )

    async def _optimize_with_preemption(
        self,
        agent_id: str,
        examples: list,
    ) -> EvolutionCycleResult:
        """Run optimization with preemption support.

        Args:
            agent_id: Agent to optimize
            examples: Training examples

        Returns:
            EvolutionCycleResult

        Raises:
            PreemptedError: If preempted by high-priority job
        """
        from ...models.optimization import get_optimizer, OptimizationStrategy

        # Get strategy
        try:
            strategy = OptimizationStrategy[self.config.strategy.upper()]
        except KeyError:
            strategy = OptimizationStrategy.APO

        # Use parallel optimizer if parallel mode is enabled
        optimizer = get_optimizer(strategy, parallel=self.config.parallel)

        # Increase timeout for parallel mode (more work done per cycle)
        timeout = 600 if self.config.parallel else 300

        # Run with preemption wrapper
        async def optimize():
            return await optimizer.optimize(
                agent_id=agent_id,
                task_examples=examples,
                num_candidates=self.config.candidates_per_cycle,
                num_iterations=1,  # Single iteration per cycle
            )

        result = await self._preemption_manager.run_with_preemption(
            optimize(),
            timeout=timeout,
        )

        return EvolutionCycleResult(
            agent_id=agent_id,
            success=result.success,
            improvement_percent=result.improvement_percent,
            new_version_id=result.new_version_id,
            baseline_score=result.baseline_score,
            best_score=result.best_candidate_score,
            examples_used=len(examples),
            candidates_evaluated=result.num_candidates,
        )

    async def _notify_cycle_complete(self, result: EvolutionCycleResult) -> None:
        """Notify callbacks of cycle completion."""
        for callback in self._on_cycle_complete:
            try:
                await callback(result)
            except Exception as e:
                logger.warning(f"Cycle callback error: {e}")

    async def _log_cycle_to_db(
        self,
        result: EvolutionCycleResult,
        trigger_type: str = "idle",
        version_before: str | None = None,
    ) -> None:
        """Log evolution cycle to database for tracking.

        Args:
            result: Cycle result
            trigger_type: What triggered this cycle
            version_before: Version ID before optimization
        """
        try:
            import asyncpg
            import os

            from ...core.config import get_database_url
            url = get_database_url()

            conn = await asyncpg.connect(url)
            try:
                import json

                # Build training_scores JSON with details
                training_scores = {
                    "baseline_score": result.baseline_score,
                    "best_score": result.best_score,
                    "examples_used": result.examples_used,
                    "candidates_evaluated": result.candidates_evaluated,
                }
                if result.error:
                    training_scores["error"] = result.error

                await conn.execute(
                    """
                    INSERT INTO evolution_cycles
                    (agent_id, version_before, version_after, strategy, trigger_type,
                     success, improvement_percent, duration_ms, preempted,
                     training_scores, completed_at)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, NOW())
                    """,
                    result.agent_id,
                    version_before,
                    result.new_version_id,
                    self.config.strategy,
                    trigger_type,
                    result.success,
                    result.improvement_percent,
                    result.duration_ms,
                    result.preempted,
                    json.dumps(training_scores),
                )
                logger.debug(f"Logged evolution cycle to DB: {result.agent_id}")
            finally:
                await conn.close()

        except Exception as e:
            # Don't fail the cycle just because logging failed
            logger.warning(f"Failed to log cycle to DB: {e}")

    async def _run_ideation_cycle(self) -> None:
        """Run a task ideation cycle.

        Generates new reasoning task concepts and creates drafts.
        Called periodically based on ideation_cycle_interval.
        """
        logger.info("Starting task ideation cycle")

        try:
            # Lazy-load the ideation agent
            if self._ideation_agent is None:
                from .task_ideation import get_task_ideation_agent
                self._ideation_agent = await get_task_ideation_agent()

            ideation_agent = self._ideation_agent  # Bind for closure with narrowed type

            # Run ideation with preemption support
            async def run_ideation():
                return await ideation_agent.run_ideation_cycle(
                    max_concepts=self.config.max_ideation_concepts,
                    novelty_threshold=self.config.min_novelty_threshold,
                    save_drafts=True,
                )

            drafts = await self._preemption_manager.run_with_preemption(
                run_ideation(),
                timeout=300,  # 5 minute timeout for ideation
            )

            # Update metrics
            self._ideation_cycles_completed += 1
            self._last_ideation_at = datetime.now()
            self._drafts_created += len(drafts)

            if drafts:
                logger.info(
                    f"Ideation cycle created {len(drafts)} task drafts: "
                    f"{', '.join(d.name for d in drafts)}"
                )

                # Generate TASK_IDEA thoughts for cognition
                await self._generate_task_idea_thoughts(drafts)
            else:
                logger.info("Ideation cycle completed - no novel tasks generated")

        except PreemptedError as e:
            logger.info(f"Ideation preempted: {e.reason}")
        except Exception as e:
            logger.error(f"Ideation cycle failed: {e}")

    async def _generate_task_idea_thoughts(self, drafts: list) -> None:
        """Generate TASK_IDEA thoughts for created drafts.

        Args:
            drafts: List of ReasoningTaskDraft created during ideation
        """
        try:
            from ..cognition import ThoughtType, Thought, get_cognition_agent

            agent = get_cognition_agent()

            for draft in drafts:
                thought = Thought(
                    thought_type=ThoughtType.TASK_IDEA,
                    title=f"New reasoning task: {draft.name}",
                    content=(
                        f"Generated a new reasoning task concept:\n\n"
                        f"**{draft.name}**\n\n"
                        f"{draft.description}\n\n"
                        f"Tags: {', '.join(draft.tags)}\n"
                        f"Examples: {len(draft.examples)}"
                    ),
                    summary=f"Created task '{draft.name}' targeting {draft.tags[0] if draft.tags else 'reasoning'}",
                    domains=["reasoning"],
                    salience=0.7,
                    confidence=0.8,
                    novelty=0.9,
                )

                await agent._save_thought(thought)
                logger.debug(f"Generated TASK_IDEA thought for {draft.name}")

        except Exception as e:
            # Don't fail ideation if thought generation fails
            logger.warning(f"Failed to generate task idea thoughts: {e}")

    async def _run_merge_cycle(self) -> None:
        """Run a model merge cycle.

        Merges top-performing agent versions to create improved models.
        Called periodically based on merge_cycle_interval.
        """
        logger.info("Starting model merge cycle")

        try:
            # Lazy-load the merge coordinator
            if self._merge_coordinator is None:
                from .merge_coordinator import get_merge_coordinator, MergeCoordinatorConfig
                self._merge_coordinator = get_merge_coordinator(
                    MergeCoordinatorConfig(
                        min_version_score=self.config.merge_min_score,
                        min_improvement=self.config.merge_min_improvement,
                    )
                )

            merge_coordinator = self._merge_coordinator  # Bind for closure with narrowed type

            # Run merge cycle for each agent in rotation
            results = []
            for agent_id in self.config.agents:
                async def run_merge(aid: str = agent_id):
                    return await merge_coordinator.run_merge_cycle(aid)

                try:
                    result = await self._preemption_manager.run_with_preemption(
                        run_merge(),
                        timeout=300,  # 5 minute timeout for merge
                    )
                    results.append(result)
                except PreemptedError as e:
                    logger.info(f"Merge preempted for {agent_id}: {e.reason}")
                    break

            # Update metrics
            self._merge_cycles_completed += 1
            self._last_merge_at = datetime.now()
            successful = [r for r in results if r.success]
            self._models_merged += len(successful)

            if successful:
                logger.info(
                    f"Merge cycle completed: {len(successful)}/{len(results)} agents merged"
                )
            else:
                logger.info("Merge cycle completed - no agents had enough candidates")

        except PreemptedError as e:
            logger.info(f"Merge preempted: {e.reason}")
        except Exception as e:
            logger.error(f"Merge cycle failed: {e}")

    async def _run_calibration_cycle(self) -> None:
        """Run a calibration cycle using external models.

        Validates intrinsic verification scores against frontier model
        judgments (Cerebras preferred, XAI fallback) to detect drift.
        """
        logger.info("Starting calibration cycle (outer loop)")

        try:
            # Generate held-out tasks from objectives
            held_out_tasks = await self.objective_generator.get_held_out_tasks(
                sample_size=20,
            )

            if len(held_out_tasks) < 10:
                logger.info("Calibration skipped - insufficient held-out tasks")
                return

            # Compute intrinsic scores for held-out tasks
            intrinsic_scores = []
            for task in held_out_tasks:
                # Simple intrinsic scoring - just check if task is verifiable
                if task.context and task.context.startswith("objective:"):
                    objective_name = task.context.split(":", 1)[1]
                    try:
                        score_result = await self.daemon_oracle.verify_objective(
                            objective_name=objective_name,
                        )
                        intrinsic_scores.append(score_result.accuracy)
                    except Exception as e:
                        logger.debug(f"Intrinsic scoring failed: {e}")
                        intrinsic_scores.append(0.5)
                else:
                    intrinsic_scores.append(0.5)

            # Run calibration against external model
            async def run_calibration():
                return await self.calibration_oracle.run_calibration(
                    held_out_tasks=held_out_tasks,
                    intrinsic_scores=intrinsic_scores,
                )

            result = await self._preemption_manager.run_with_preemption(
                run_calibration(),
                timeout=300,
            )

            # Update metrics
            self._calibration_cycles_completed += 1
            self._last_calibration_at = datetime.now()

            # Log results
            if result.drift_detected:
                logger.warning(
                    f"Calibration detected drift: severity={result.drift_severity}, "
                    f"correlation={result.correlation:.2f}, bias={result.bias:+.2f}"
                )
            else:
                logger.info(
                    f"Calibration complete: correlation={result.correlation:.2f}, "
                    f"bias={result.bias:+.2f}, provider={result.external_provider}"
                )

            # Log to database
            await self._log_calibration_to_db(result)

        except PreemptedError as e:
            logger.info(f"Calibration preempted: {e.reason}")
        except Exception as e:
            logger.error(f"Calibration cycle failed: {e}")

    async def _log_calibration_to_db(self, result) -> None:
        """Log calibration result to database.

        Args:
            result: CalibrationResult from calibration oracle
        """
        try:
            import asyncpg
            import json
            import os

            from ...core.config import get_database_url
            url = get_database_url()

            conn = await asyncpg.connect(url)
            try:
                await conn.execute(
                    """
                    INSERT INTO evolution_calibrations
                    (tasks_evaluated, correlation, mean_absolute_error, bias,
                     drift_detected, drift_severity, external_provider, external_model,
                     duration_ms, calibrated_at)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, NOW())
                    """,
                    result.tasks_evaluated,
                    result.correlation,
                    result.mean_absolute_error,
                    result.bias,
                    result.drift_detected,
                    result.drift_severity,
                    result.external_provider,
                    result.external_model,
                    result.duration_ms,
                )
                logger.debug("Logged calibration result to DB")
            finally:
                await conn.close()

        except Exception as e:
            # Don't fail calibration just because logging failed
            logger.warning(f"Failed to log calibration to DB: {e}")

    async def force_merge_cycle(self, agent_id: str | None = None) -> dict:
        """Force an immediate merge cycle.

        Bypasses the interval check and runs merge immediately.

        Args:
            agent_id: Specific agent to merge (None = all agents)

        Returns:
            Dict with merge results
        """
        logger.info(f"Forcing merge cycle{f' for {agent_id}' if agent_id else ''}")

        if self._merge_coordinator is None:
            from .merge_coordinator import get_merge_coordinator, MergeCoordinatorConfig
            self._merge_coordinator = get_merge_coordinator(
                MergeCoordinatorConfig(
                    min_version_score=self.config.merge_min_score,
                    min_improvement=self.config.merge_min_improvement,
                )
            )

        results = {}
        agents = [agent_id] if agent_id else self.config.agents

        for agent in agents:
            result = await self._merge_coordinator.run_merge_cycle(agent)
            results[agent] = result.to_dict()

            if result.success:
                self._models_merged += 1

        # Update metrics
        self._merge_cycles_completed += 1
        self._last_merge_at = datetime.now()

        return results

    async def force_ideation_cycle(self) -> list:
        """Force an immediate ideation cycle.

        Bypasses the interval check and runs ideation immediately.

        Returns:
            List of ReasoningTaskDraft created
        """
        logger.info("Forcing task ideation cycle")

        if self._ideation_agent is None:
            from .task_ideation import get_task_ideation_agent
            self._ideation_agent = await get_task_ideation_agent()

        drafts = await self._ideation_agent.run_ideation_cycle(
            max_concepts=self.config.max_ideation_concepts,
            novelty_threshold=self.config.min_novelty_threshold,
            save_drafts=True,
        )

        # Update metrics
        self._ideation_cycles_completed += 1
        self._last_ideation_at = datetime.now()
        self._drafts_created += len(drafts)

        if drafts:
            await self._generate_task_idea_thoughts(drafts)

        return drafts


# Module-level singleton
_evolution_daemon: EvolutionDaemon | None = None


def get_evolution_daemon(config: EvolutionConfig | None = None) -> EvolutionDaemon:
    """Get or create evolution daemon singleton.

    Args:
        config: Optional config (only used on first call)

    Returns:
        EvolutionDaemon instance
    """
    global _evolution_daemon
    if _evolution_daemon is None:
        _evolution_daemon = EvolutionDaemon(config)
    return _evolution_daemon
