"""Evolution service for agent prompt optimization.

Daemon that monitors GPU idle state and triggers evolution cycles
to optimize agent system prompts.

BDD Alignment (swarm_evolution.feature):
- Start evolution daemon with '/evolve start'
- Evolution daemon monitors GPU idle state
- Evolution respects rate limits
- Stop evolution daemon with '/evolve stop'
- Manual evolution trigger with '/evolve trigger'
- Evolution cycle optimizes agent prompt
- Evolution cycle uses GEPA strategy
- Evolution cycle records to database
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


class EvolutionStrategy(Enum):
    """Optimization strategy for evolution cycles."""

    APO = "apo"  # Automatic Prompt Optimization
    GEPA = "gepa"  # Genetic Evolution for Prompt Adaptation
    HYBRID = "hybrid"  # Combination approach


class CycleStatus(Enum):
    """Status of an evolution cycle."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class EvolutionCycle:
    """Record of an evolution cycle.

    BDD: "Evolution cycle records to database"
    - Timestamp
    - Agent
    - Status (success/failure)
    - Improvement percentage
    - Duration
    """

    id: str
    agent_id: str
    strategy: EvolutionStrategy
    status: CycleStatus = CycleStatus.PENDING
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    # Results
    examples_used: int = 0
    candidates_generated: int = 0
    improvement_pct: float = 0.0
    best_score: float = 0.0
    baseline_score: float = 0.0

    # Error tracking
    error_message: Optional[str] = None

    @property
    def duration_ms(self) -> int:
        """Duration of the cycle in milliseconds."""
        if not self.started_at:
            return 0
        end = self.completed_at or datetime.now()
        return int((end - self.started_at).total_seconds() * 1000)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for storage/display."""
        return {
            "id": self.id,
            "agent_id": self.agent_id,
            "strategy": self.strategy.value,
            "status": self.status.value,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "duration_ms": self.duration_ms,
            "examples_used": self.examples_used,
            "candidates_generated": self.candidates_generated,
            "improvement_pct": self.improvement_pct,
            "best_score": self.best_score,
            "baseline_score": self.baseline_score,
            "error_message": self.error_message,
        }


@dataclass
class EvolutionConfig:
    """Configuration for evolution daemon.

    BDD: "Evolution respects rate limits"
    - max_cycles_per_hour
    """

    # Rate limiting
    max_cycles_per_hour: int = 4
    min_idle_seconds: int = 60  # GPU must be idle for this long

    # Agent rotation
    agent_rotation: list[str] = field(
        default_factory=lambda: ["leader", "risk", "optimizer", "critic"]
    )

    # Evolution parameters
    min_training_examples: int = 5  # BDD: "Minimum examples required"
    num_candidates: int = 5
    num_iterations: int = 3

    # GPU idle threshold
    idle_threshold: float = 0.2  # 20%

    # Strategy
    default_strategy: EvolutionStrategy = EvolutionStrategy.APO


class EvolutionService:
    """Evolution daemon for agent optimization.

    Monitors GPU utilization and triggers evolution cycles when
    resources are idle. Manages agent rotation and rate limiting.

    BDD Scenarios Supported:
    - Start/stop evolution daemon
    - GPU idle monitoring
    - Rate limiting
    - Manual trigger
    - GEPA/APO strategies
    - Training data requirements
    """

    def __init__(
        self,
        config: EvolutionConfig,
        get_gpu_idle: Callable[[], bool],
        get_scheduler: Optional[Callable] = None,
    ):
        """Initialize evolution service.

        Args:
            config: Evolution configuration
            get_gpu_idle: Function to check if GPU is idle
            get_scheduler: Optional function to get scheduler for inference
        """
        self.config = config
        self._get_gpu_idle = get_gpu_idle
        self._get_scheduler = get_scheduler

        # Daemon state
        self._running = False
        self._daemon_task: Optional[asyncio.Task] = None

        # Cycle tracking
        self._cycle_counter = 0
        self._cycles: list[EvolutionCycle] = []
        self._current_cycle: Optional[EvolutionCycle] = None

        # Rate limiting
        self._recent_cycles: list[datetime] = []

        # Agent rotation
        self._rotation_index = 0

        # Callbacks
        self._progress_callbacks: list[Callable] = []

        logger.info("EvolutionService initialized")

    # ─────────────────────────────────────────────────────────────────────────
    # Daemon Lifecycle (BDD: Start/Stop evolution daemon)
    # ─────────────────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Start the evolution daemon.

        BDD: "Start evolution daemon with '/evolve start'"
        """
        if self._running:
            logger.warning("Evolution daemon already running")
            return

        self._running = True
        self._daemon_task = asyncio.create_task(self._daemon_loop())

        logger.info("Evolution daemon started")

    async def stop(self) -> None:
        """Stop the evolution daemon.

        BDD: "Stop evolution daemon with '/evolve stop'"
        - Evolution daemon should stop
        - GPU endpoints should remain available
        """
        if not self._running:
            return

        self._running = False

        if self._daemon_task:
            self._daemon_task.cancel()
            try:
                await self._daemon_task
            except asyncio.CancelledError:
                pass

        logger.info("Evolution daemon stopped")

    async def _daemon_loop(self) -> None:
        """Background daemon loop.

        BDD: "Evolution daemon monitors GPU idle state"
        - When GPU utilization drops below 20%
        - An evolution cycle should be triggered
        """
        idle_start: Optional[datetime] = None

        while self._running:
            try:
                is_idle = self._get_gpu_idle()

                if is_idle:
                    if idle_start is None:
                        idle_start = datetime.now()
                        logger.debug("GPU became idle")

                    # Check if idle long enough
                    idle_duration = (datetime.now() - idle_start).total_seconds()
                    if idle_duration >= self.config.min_idle_seconds:
                        # Check rate limit
                        if self._can_run_cycle():
                            # Trigger evolution for next agent
                            agent_id = self._get_next_agent()
                            await self._run_cycle(agent_id)
                            idle_start = None  # Reset idle timer
                else:
                    idle_start = None

            except Exception as e:
                logger.error(f"Daemon loop error: {e}")

            await asyncio.sleep(5)  # Check every 5 seconds

    # ─────────────────────────────────────────────────────────────────────────
    # Rate Limiting (BDD: Evolution respects rate limits)
    # ─────────────────────────────────────────────────────────────────────────

    def _can_run_cycle(self) -> bool:
        """Check if another cycle can run within rate limits.

        BDD: "Evolution respects rate limits"
        - Respects max_cycles_per_hour setting
        """
        # Clean up old cycle timestamps
        cutoff = datetime.now() - timedelta(hours=1)
        self._recent_cycles = [t for t in self._recent_cycles if t > cutoff]

        return len(self._recent_cycles) < self.config.max_cycles_per_hour

    def _record_cycle_start(self) -> None:
        """Record that a cycle has started for rate limiting."""
        self._recent_cycles.append(datetime.now())

    def _get_next_agent(self) -> str:
        """Get next agent in rotation.

        BDD: "Next agent in rotation should be optimized"
        """
        agents = self.config.agent_rotation
        if not agents:
            return "leader"

        agent = agents[self._rotation_index % len(agents)]
        self._rotation_index += 1
        return agent

    # ─────────────────────────────────────────────────────────────────────────
    # Evolution Cycles (BDD: Evolution cycle optimizes agent prompt)
    # ─────────────────────────────────────────────────────────────────────────

    async def trigger(self, agent_id: Optional[str] = None) -> dict[str, Any]:
        """Manually trigger evolution for an agent.

        BDD: "Manual evolution trigger with '/evolve trigger'"
        - Cycle should start immediately
        - Cycle should bypass idle check

        Args:
            agent_id: Agent to evolve (None = next in rotation)

        Returns:
            Cycle result
        """
        if agent_id is None:
            agent_id = self._get_next_agent()

        logger.info(f"Manual evolution trigger for {agent_id}")

        return await self._run_cycle(agent_id)

    async def _run_cycle(
        self,
        agent_id: str,
        strategy: Optional[EvolutionStrategy] = None,
    ) -> dict[str, Any]:
        """Run an evolution cycle.

        BDD: "Evolution cycle optimizes agent prompt"
        1. Collect training examples
        2. Generate prompt candidates
        3. Evaluate candidates
        4. Save improved version if better

        Args:
            agent_id: Agent to optimize
            strategy: Strategy to use (default from config)

        Returns:
            Cycle result dict
        """
        strategy = strategy or self.config.default_strategy

        # Create cycle record
        self._cycle_counter += 1
        cycle = EvolutionCycle(
            id=f"cycle-{self._cycle_counter}",
            agent_id=agent_id,
            strategy=strategy,
        )
        self._current_cycle = cycle
        self._cycles.append(cycle)

        # Record for rate limiting
        self._record_cycle_start()

        try:
            cycle.started_at = datetime.now()
            cycle.status = CycleStatus.RUNNING

            self._notify_progress(f"Starting evolution for {agent_id}")

            # Step 1: Collect training examples
            examples = await self._collect_examples(agent_id)
            cycle.examples_used = len(examples)

            # Check minimum examples requirement
            if len(examples) < self.config.min_training_examples:
                cycle.status = CycleStatus.SKIPPED
                cycle.error_message = (
                    f"Insufficient examples: {len(examples)} < "
                    f"{self.config.min_training_examples}"
                )
                cycle.completed_at = datetime.now()
                logger.warning(f"Skipping {agent_id}: {cycle.error_message}")
                return cycle.to_dict()

            # Step 2: Get baseline score
            cycle.baseline_score = await self._evaluate_current(agent_id, examples)
            self._notify_progress(f"Baseline score: {cycle.baseline_score:.3f}")

            # Step 3: Generate and evaluate candidates
            if strategy == EvolutionStrategy.GEPA:
                best_score, improvement = await self._run_gepa(
                    agent_id, examples, cycle.baseline_score
                )
            else:
                best_score, improvement = await self._run_apo(
                    agent_id, examples, cycle.baseline_score
                )

            cycle.best_score = best_score
            cycle.improvement_pct = improvement

            # Step 4: Save if improved
            if improvement > 0:
                await self._save_improved_version(agent_id, cycle)
                self._notify_progress(
                    f"Saved improved version: +{improvement:.1f}%"
                )

            cycle.status = CycleStatus.COMPLETED
            cycle.completed_at = datetime.now()

            logger.info(
                f"Evolution cycle completed for {agent_id}: "
                f"{improvement:+.1f}% in {cycle.duration_ms}ms"
            )

        except Exception as e:
            cycle.status = CycleStatus.FAILED
            cycle.error_message = str(e)
            cycle.completed_at = datetime.now()
            logger.error(f"Evolution cycle failed: {e}")

        finally:
            self._current_cycle = None

        return cycle.to_dict()

    async def _collect_examples(self, agent_id: str) -> list[dict[str, Any]]:
        """Collect training examples for an agent.

        BDD: "Training examples collected from swarm runs"
        BDD: "Bootstrap examples from held-out queries"

        Returns:
            List of training examples
        """
        # In a real implementation, this would query the database
        # for recent high-quality outputs from this agent
        logger.debug(f"Collecting training examples for {agent_id}")

        # Placeholder: return empty list (requires database integration)
        return []

    async def _evaluate_current(
        self, agent_id: str, examples: list[dict]
    ) -> float:
        """Evaluate current prompt against examples.

        Returns:
            Score (0-1)
        """
        # Placeholder: would use scheduler to run evaluation
        return 0.5

    async def _run_apo(
        self,
        agent_id: str,
        examples: list[dict],
        baseline: float,
    ) -> tuple[float, float]:
        """Run APO (Automatic Prompt Optimization).

        BDD: "Generate prompt candidates"
        BDD: "Evaluate candidates"

        Returns:
            (best_score, improvement_percentage)
        """
        logger.debug(f"Running APO for {agent_id}")

        # Placeholder: would generate candidates and evaluate
        # For now, simulate slight improvement
        best_score = baseline
        return (best_score, 0.0)

    async def _run_gepa(
        self,
        agent_id: str,
        examples: list[dict],
        baseline: float,
    ) -> tuple[float, float]:
        """Run GEPA (Genetic Evolution for Prompt Adaptation).

        BDD: "Evolution cycle uses GEPA strategy"
        - Pareto-optimal candidates should be identified
        - Multiple objectives should be balanced

        Returns:
            (best_score, improvement_percentage)
        """
        logger.debug(f"Running GEPA for {agent_id}")

        # GEPA uses multi-objective optimization
        # Objectives: accuracy, coherence, relevance, completeness, clarity

        # Placeholder: would run genetic algorithm
        best_score = baseline
        return (best_score, 0.0)

    async def _save_improved_version(
        self, agent_id: str, cycle: EvolutionCycle
    ) -> None:
        """Save improved agent version.

        BDD: "Save improved version if better"
        """
        logger.info(
            f"Saving improved version for {agent_id}: "
            f"{cycle.baseline_score:.3f} → {cycle.best_score:.3f}"
        )
        # Placeholder: would save to agent version store

    # ─────────────────────────────────────────────────────────────────────────
    # Progress Notification
    # ─────────────────────────────────────────────────────────────────────────

    def subscribe_progress(self, callback: Callable[[str], None]) -> None:
        """Subscribe to progress updates."""
        self._progress_callbacks.append(callback)

    def unsubscribe_progress(self, callback: Callable) -> None:
        """Unsubscribe from progress updates."""
        if callback in self._progress_callbacks:
            self._progress_callbacks.remove(callback)

    def _notify_progress(self, message: str) -> None:
        """Notify subscribers of progress."""
        for callback in self._progress_callbacks:
            try:
                callback(message)
            except Exception as e:
                logger.error(f"Progress callback error: {e}")

    # ─────────────────────────────────────────────────────────────────────────
    # Status (BDD: Evolution panel shows daemon status)
    # ─────────────────────────────────────────────────────────────────────────

    def get_status(self) -> dict[str, Any]:
        """Get evolution daemon status.

        BDD: "Evolution panel shows daemon status"
        - Status: RUNNING or STOPPED
        - Cycles: Total completed cycles
        - Improvement: Cumulative improvement %
        - Next Agent: Next in rotation
        """
        completed_cycles = [
            c for c in self._cycles if c.status == CycleStatus.COMPLETED
        ]
        total_improvement = sum(c.improvement_pct for c in completed_cycles)

        return {
            "running": self._running,
            "status": "RUNNING" if self._running else "STOPPED",
            "total_cycles": len(self._cycles),
            "completed_cycles": len(completed_cycles),
            "failed_cycles": len(
                [c for c in self._cycles if c.status == CycleStatus.FAILED]
            ),
            "skipped_cycles": len(
                [c for c in self._cycles if c.status == CycleStatus.SKIPPED]
            ),
            "cumulative_improvement_pct": total_improvement,
            "next_agent": self._get_next_agent_preview(),
            "cycles_this_hour": len(self._recent_cycles),
            "max_cycles_per_hour": self.config.max_cycles_per_hour,
            "current_cycle": (
                self._current_cycle.to_dict() if self._current_cycle else None
            ),
        }

    def _get_next_agent_preview(self) -> str:
        """Get next agent without advancing rotation."""
        agents = self.config.agent_rotation
        if not agents:
            return "leader"
        return agents[self._rotation_index % len(agents)]

    def get_recent_cycles(self, limit: int = 10) -> list[dict[str, Any]]:
        """Get recent evolution cycles.

        BDD: "Evolution panel shows recent cycles"
        - Timestamp
        - Agent
        - Status (✓ or ✗)
        - Improvement (+X.X%)
        - Duration

        Args:
            limit: Maximum cycles to return

        Returns:
            List of cycle dicts
        """
        recent = self._cycles[-limit:] if self._cycles else []
        return [c.to_dict() for c in reversed(recent)]

    def get_agent_scores(self) -> dict[str, dict[str, Any]]:
        """Get per-agent evolution scores.

        BDD: "Evolution panel shows agent scores"
        - Training vs held-out scores
        - Trends (↗ ↘ →)

        Returns:
            Dict mapping agent_id to score info
        """
        scores = {}

        for agent_id in self.config.agent_rotation:
            agent_cycles = [
                c
                for c in self._cycles
                if c.agent_id == agent_id and c.status == CycleStatus.COMPLETED
            ]

            if not agent_cycles:
                scores[agent_id] = {
                    "current_score": 0.0,
                    "improvement": 0.0,
                    "trend": "→",
                    "cycles": 0,
                }
            else:
                recent = agent_cycles[-3:]  # Last 3 cycles for trend
                improvements = [c.improvement_pct for c in recent]

                if len(improvements) >= 2:
                    if improvements[-1] > improvements[-2]:
                        trend = "↗"
                    elif improvements[-1] < improvements[-2]:
                        trend = "↘"
                    else:
                        trend = "→"
                else:
                    trend = "→"

                scores[agent_id] = {
                    "current_score": agent_cycles[-1].best_score,
                    "improvement": sum(c.improvement_pct for c in agent_cycles),
                    "trend": trend,
                    "cycles": len(agent_cycles),
                }

        return scores

    @property
    def is_running(self) -> bool:
        """Whether daemon is running."""
        return self._running
