"""Central evolution engine implementing Atropos-style patterns.

Provides the core evolution loop with proper agent invocation, scoring,
and trajectory collection. Designed for internal use by the daemon,
with the atropos_env adapter providing external trainer compatibility.

Key Atropos patterns implemented:
- get_next_item(): Select task from held-out pool
- collect_trajectory(): Run agent with variations, capture outputs
- score(): Binary task completion scoring
- evaluate(): Aggregate trajectory results

Usage:
    from gaius.agents.evolution.engine import EvolutionEngine, get_engine

    engine = await get_engine()

    # Run a single evolution cycle
    result = await engine.run_evolution_cycle("leader")
    if result.success:
        print(f"Improved by {result.improvement_percent:.1f}%")
"""

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

from .runner import AgentRunner, AgentResult, get_runner
from ...models.versioning import AgentConfig, get_version_manager

logger = logging.getLogger(__name__)


@dataclass
class TaskItem:
    """A task item for evolution evaluation.

    Corresponds to Atropos's data item structure.
    """

    id: str
    prompt: str
    domain: str = ""
    category: str = ""
    expected_output: Optional[str] = None
    context: str = ""
    evaluation_criteria: str = ""
    reference_score: Optional[float] = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "prompt": self.prompt,
            "domain": self.domain,
            "category": self.category,
            "expected_output": self.expected_output,
            "context": self.context,
            "evaluation_criteria": self.evaluation_criteria,
            "reference_score": self.reference_score,
        }


@dataclass
class Trajectory:
    """A trajectory from agent execution.

    Captures the input, output, and scoring for one task execution.
    Corresponds to Atropos's ScoredDataItem.
    """

    task_id: str
    prompt: str
    output: str
    score: float
    success: bool

    # Metadata
    tokens_used: int = 0
    latency_ms: int = 0
    model: str = ""
    error: Optional[str] = None

    # Scoring breakdown
    task_completed: bool = False
    quality_score: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "task_id": self.task_id,
            "prompt": self.prompt,
            "output": self.output,
            "score": self.score,
            "success": self.success,
            "tokens_used": self.tokens_used,
            "latency_ms": self.latency_ms,
            "model": self.model,
            "error": self.error,
            "task_completed": self.task_completed,
            "quality_score": self.quality_score,
        }


@dataclass
class CycleResult:
    """Result from an evolution cycle.

    Provides detailed metrics for logging and debugging.
    """

    agent_id: str
    success: bool
    improvement_percent: float = 0.0
    new_version_id: Optional[str] = None
    baseline_score: float = 0.0
    best_score: float = 0.0

    # Trajectory details
    trajectories_run: int = 0
    trajectories_succeeded: int = 0
    trajectories_failed: int = 0
    total_tokens: int = 0
    total_latency_ms: int = 0

    # Timing
    duration_ms: int = 0
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    # Error info
    error: Optional[str] = None
    preempted: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "agent_id": self.agent_id,
            "success": self.success,
            "improvement_percent": self.improvement_percent,
            "new_version_id": self.new_version_id,
            "baseline_score": self.baseline_score,
            "best_score": self.best_score,
            "trajectories_run": self.trajectories_run,
            "trajectories_succeeded": self.trajectories_succeeded,
            "trajectories_failed": self.trajectories_failed,
            "total_tokens": self.total_tokens,
            "total_latency_ms": self.total_latency_ms,
            "duration_ms": self.duration_ms,
            "error": self.error,
            "preempted": self.preempted,
        }


class EvolutionEngine:
    """Central evolution engine with Atropos-style patterns.

    Implements the core loop:
    1. Get tasks from held-out pool
    2. Run trajectories (agent execution + scoring)
    3. Aggregate scores
    4. Update agent if improved

    Uses AgentRunner for all inference, ensuring outputs are validated
    and empty results are properly handled as failures.
    """

    def __init__(
        self,
        runner: Optional[AgentRunner] = None,
        min_improvement_threshold: float = 0.05,
    ):
        """Initialize engine.

        Args:
            runner: AgentRunner for inference (lazy-loaded if None)
            min_improvement_threshold: Minimum improvement to save new version
        """
        self._runner = runner
        self._min_improvement = min_improvement_threshold
        self._version_manager = None

    async def _ensure_initialized(self) -> None:
        """Ensure dependencies are initialized."""
        if self._runner is None:
            self._runner = await get_runner()
        if self._version_manager is None:
            self._version_manager = get_version_manager()

    async def generate_items(
        self,
        agent_id: str,
        count: int = 10,
    ) -> list[TaskItem]:
        """Generate task items for evaluation.

        Tries to pull from held-out pool first, then falls back to
        generating synthetic evaluation tasks.

        Args:
            agent_id: Agent to generate tasks for
            count: Number of tasks to generate

        Returns:
            List of TaskItem for evaluation
        """
        items = []

        # Try to get from held-out pool
        try:
            from .evaluation import get_held_out_manager

            manager = get_held_out_manager()
            held_out = await manager.get_sample(size=count)

            for i, query in enumerate(held_out):
                items.append(TaskItem(
                    id=f"held_out_{i}",
                    prompt=query.input_prompt,
                    domain=query.domain,
                    category=query.category,
                    expected_output=query.expected_output,
                    context=query.context or "",
                ))

        except Exception as e:
            logger.debug(f"Could not load held-out items: {e}")

        # If not enough items, generate synthetic ones
        if len(items) < count:
            remaining = count - len(items)
            synthetic = self._generate_synthetic_tasks(agent_id, remaining)
            items.extend(synthetic)

        return items[:count]

    def _generate_synthetic_tasks(
        self,
        agent_id: str,
        count: int,
    ) -> list[TaskItem]:
        """Generate synthetic evaluation tasks.

        Creates tasks appropriate for the agent type (leader, critic, etc.)

        Args:
            agent_id: Agent type
            count: Number to generate

        Returns:
            List of synthetic TaskItem
        """
        # Base prompts by agent type
        task_templates = {
            "leader": [
                "Analyze this domain and provide strategic recommendations: {topic}",
                "What are the key considerations for {topic}?",
                "Summarize the current state and opportunities in {topic}",
            ],
            "critic": [
                "Evaluate this analysis for weaknesses: {analysis}",
                "What are the potential risks in this approach: {approach}",
                "Identify gaps in this reasoning: {reasoning}",
            ],
            "risk": [
                "Assess the risks associated with {topic}",
                "What could go wrong with {approach}?",
                "Identify potential failure modes for {system}",
            ],
            "opportunity": [
                "What opportunities exist in {topic}?",
                "How could {approach} be leveraged for growth?",
                "Identify potential synergies with {system}",
            ],
            "domain": [
                "Explain the key concepts in {topic}",
                "How does {concept} relate to {other_concept}?",
                "What are the fundamentals of {topic}?",
            ],
        }

        # Get templates for this agent type
        templates = task_templates.get(agent_id, task_templates["leader"])

        # Sample topics
        topics = [
            "pension fund management",
            "distributed systems",
            "machine learning infrastructure",
            "knowledge graphs",
            "real-time analytics",
        ]

        items = []
        import random

        for i in range(count):
            template = random.choice(templates)
            topic = random.choice(topics)

            # Fill in template
            prompt = template.format(
                topic=topic,
                analysis=f"Analysis of {topic}",
                approach=f"Current approach to {topic}",
                reasoning=f"Reasoning about {topic}",
                concept=topic.split()[0],
                other_concept=topic.split()[-1] if len(topic.split()) > 1 else topic,
                system=f"{topic} system",
            )

            items.append(TaskItem(
                id=f"synthetic_{i}",
                prompt=prompt,
                domain="general",
                category="synthetic",
            ))

        return items

    async def run_trajectory(
        self,
        config: AgentConfig,
        item: TaskItem,
    ) -> Trajectory:
        """Run a single trajectory (agent execution + scoring).

        Uses AgentRunner for validated inference. Scores using
        binary task completion with quality gradient.

        Args:
            config: Agent configuration
            item: Task to execute

        Returns:
            Trajectory with output and score
        """
        await self._ensure_initialized()
        assert self._runner is not None  # Guaranteed by _ensure_initialized

        # Run agent
        result = await self._runner.invoke(config, item.prompt)

        # Score the result
        if not result.success:
            # Failed execution = score 0.0
            return Trajectory(
                task_id=item.id,
                prompt=item.prompt,
                output=result.content,
                score=0.0,
                success=False,
                tokens_used=result.tokens_used,
                latency_ms=result.latency_ms,
                model=result.model,
                error=result.error,
                task_completed=False,
                quality_score=0.0,
            )

        # Score the output
        score, task_completed, quality = await self._score_output(
            result.content, item
        )

        return Trajectory(
            task_id=item.id,
            prompt=item.prompt,
            output=result.content,
            score=score,
            success=True,
            tokens_used=result.tokens_used,
            latency_ms=result.latency_ms,
            model=result.model,
            task_completed=task_completed,
            quality_score=quality,
        )

    async def _score_output(
        self,
        output: str,
        item: TaskItem,
    ) -> tuple[float, bool, float]:
        """Score an agent output.

        Uses binary task completion with quality gradient:
        - Empty/failed = 0.0
        - Attempted but incomplete = 0.1
        - Completed with low quality = 0.5
        - Completed with high quality = 0.5-1.0

        Args:
            output: Agent output text
            item: Original task

        Returns:
            Tuple of (score, task_completed, quality_score)
        """
        # Empty output check (should not happen with AgentRunner validation)
        if not output or not output.strip():
            return 0.0, False, 0.0

        # Check basic task completion heuristics
        output_lower = output.lower()
        prompt_lower = item.prompt.lower()

        # Basic relevance check - does output address the prompt?
        # Look for key terms from the prompt in the output
        prompt_words = set(prompt_lower.split())
        output_words = set(output_lower.split())
        common_words = prompt_words & output_words
        relevance = len(common_words) / max(len(prompt_words), 1)

        # Check for substantive response (not just acknowledgment)
        is_substantive = len(output.split()) > 20  # More than 20 words
        has_structure = any(marker in output for marker in [
            "1.", "2.", "•", "-", "First", "Second", ":", "\n\n"
        ])

        # Determine task completion
        task_completed = relevance > 0.2 and is_substantive

        if not task_completed:
            # Attempted but didn't complete
            return 0.1, False, 0.0

        # Quality scoring for completed tasks
        quality_factors = []

        # Length factor (prefer comprehensive responses)
        word_count = len(output.split())
        length_score = min(word_count / 200, 1.0)  # Cap at 200 words
        quality_factors.append(length_score)

        # Structure factor
        structure_score = 0.5 if has_structure else 0.2
        quality_factors.append(structure_score)

        # Relevance factor
        quality_factors.append(min(relevance * 2, 1.0))

        quality = sum(quality_factors) / len(quality_factors)

        # Final score: 0.5 + (0.5 * quality) for completed tasks
        score = 0.5 + (0.5 * quality)

        return score, True, quality

    async def run_evolution_cycle(
        self,
        agent_id: str,
        num_items: int = 10,
    ) -> CycleResult:
        """Run a full evolution cycle for an agent.

        1. Load current agent config
        2. Generate evaluation items
        3. Run trajectories
        4. Compute aggregate score
        5. Update agent if improved

        Args:
            agent_id: Agent to evolve
            num_items: Number of items to evaluate

        Returns:
            CycleResult with outcome
        """
        await self._ensure_initialized()
        assert self._version_manager is not None  # Guaranteed by _ensure_initialized
        started_at = datetime.now()
        start_time = time.perf_counter()

        try:
            # Get current config
            version = await self._version_manager.get_active_version(agent_id)
            if version is None:
                return CycleResult(
                    agent_id=agent_id,
                    success=False,
                    error=f"No active version for agent {agent_id}",
                    started_at=started_at,
                )

            config = version.config

            # Generate items
            items = await self.generate_items(agent_id, num_items)
            if not items:
                return CycleResult(
                    agent_id=agent_id,
                    success=False,
                    error="No evaluation items available",
                    started_at=started_at,
                )

            # Run trajectories
            trajectories: list[Trajectory] = []
            total_tokens = 0
            total_latency = 0

            for item in items:
                trajectory = await self.run_trajectory(config, item)
                trajectories.append(trajectory)
                total_tokens += trajectory.tokens_used
                total_latency += trajectory.latency_ms

            # Compute aggregate score
            succeeded = [t for t in trajectories if t.success]
            failed = [t for t in trajectories if not t.success]

            if not succeeded:
                # All trajectories failed
                duration_ms = int((time.perf_counter() - start_time) * 1000)
                return CycleResult(
                    agent_id=agent_id,
                    success=False,
                    baseline_score=0.0,
                    best_score=0.0,
                    trajectories_run=len(trajectories),
                    trajectories_succeeded=0,
                    trajectories_failed=len(failed),
                    total_tokens=total_tokens,
                    total_latency_ms=total_latency,
                    duration_ms=duration_ms,
                    error="All trajectories failed",
                    started_at=started_at,
                    completed_at=datetime.now(),
                )

            avg_score = sum(t.score for t in succeeded) / len(succeeded)
            best_score = max(t.score for t in succeeded)

            # Get baseline from version metrics
            baseline_score = version.avg_overall_score or 0.5

            # Calculate improvement
            improvement = (avg_score - baseline_score) / max(baseline_score, 0.01) * 100

            duration_ms = int((time.perf_counter() - start_time) * 1000)

            # Update version metrics
            new_version_id = None
            if improvement >= self._min_improvement * 100:
                # Save updated metrics to version
                try:
                    # Use correct method signature
                    await self._version_manager.update_metrics(
                        version.version_id,
                        evaluation_score=avg_score,
                        dimension_scores={"overall": avg_score, "improvement": improvement},
                    )
                    new_version_id = version.version_id
                    logger.info(
                        f"Updated {agent_id} metrics: "
                        f"{baseline_score:.3f} -> {avg_score:.3f} "
                        f"({improvement:.1f}% improvement)"
                    )
                except Exception as e:
                    logger.warning(f"Failed to update metrics: {e}")

            return CycleResult(
                agent_id=agent_id,
                success=True,
                improvement_percent=improvement,
                new_version_id=new_version_id,
                baseline_score=baseline_score,
                best_score=best_score,
                trajectories_run=len(trajectories),
                trajectories_succeeded=len(succeeded),
                trajectories_failed=len(failed),
                total_tokens=total_tokens,
                total_latency_ms=total_latency,
                duration_ms=duration_ms,
                started_at=started_at,
                completed_at=datetime.now(),
            )

        except Exception as e:
            duration_ms = int((time.perf_counter() - start_time) * 1000)
            logger.error(f"Evolution cycle failed: {e}")
            return CycleResult(
                agent_id=agent_id,
                success=False,
                error=str(e),
                duration_ms=duration_ms,
                started_at=started_at,
                completed_at=datetime.now(),
            )

    async def health_check(self) -> dict[str, Any]:
        """Check engine health.

        Returns:
            Health status dict
        """
        await self._ensure_initialized()
        assert self._runner is not None  # Guaranteed by _ensure_initialized

        runner_healthy = await self._runner.health_check()
        vm_healthy = self._version_manager is not None

        return {
            "healthy": runner_healthy and vm_healthy,
            "runner_healthy": runner_healthy,
            "version_manager_healthy": vm_healthy,
        }


# Module-level singleton
_engine: Optional[EvolutionEngine] = None


async def get_engine() -> EvolutionEngine:
    """Get or create the EvolutionEngine singleton.

    Returns:
        EvolutionEngine instance
    """
    global _engine
    if _engine is None:
        _engine = EvolutionEngine()
    return _engine


def reset_engine() -> None:
    """Reset the engine singleton (for testing)."""
    global _engine
    _engine = None
