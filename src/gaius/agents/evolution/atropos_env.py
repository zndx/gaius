"""Atropos-compatible environment adapter for Gaius evolution.

Implements the Atropos BaseEnv interface to enable compatibility with
external RL trainers while using Gaius's internal evolution infrastructure.

Atropos (by Nous Research) defines a standard interface for RL environments:
- get_next_item(): Get next task for evaluation
- collect_trajectory(): Execute task and collect results
- score(): Compute reward for trajectory
- evaluate(): Run batch evaluation

This adapter wraps EvolutionEngine to expose the Atropos interface,
enabling future integration with external trainers while keeping
all actual RL execution in the gaius-engine.

Usage:
    from gaius.agents.evolution.atropos_env import GaiusEvolutionEnv

    env = GaiusEvolutionEnv(agent_id="leader")

    # Atropos-style interface
    item = await env.get_next_item()
    trajectory = await env.collect_trajectory(item, model_output)
    score = env.score(trajectory)
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Atropos Protocol Types (matching Nous Research specification)
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class ScoredDataItem:
    """A single scored data item (Atropos protocol).

    Corresponds to a trajectory result with reward signal.
    """

    item_id: str
    prompt: str
    output: str
    score: float

    # Additional Gaius metadata
    model: str = ""
    tokens_used: int = 0
    latency_ms: int = 0
    task_completed: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "item_id": self.item_id,
            "prompt": self.prompt,
            "output": self.output,
            "score": self.score,
            "model": self.model,
            "tokens_used": self.tokens_used,
            "latency_ms": self.latency_ms,
            "task_completed": self.task_completed,
        }


@dataclass
class ScoredDataGroup:
    """A group of scored data items (Atropos protocol).

    Used for batch evaluation results.
    """

    group_id: str
    items: list[ScoredDataItem] = field(default_factory=list)
    aggregate_score: float = 0.0
    timestamp: Optional[datetime] = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()
        if self.items and self.aggregate_score == 0.0:
            self.aggregate_score = sum(i.score for i in self.items) / len(self.items)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "group_id": self.group_id,
            "items": [i.to_dict() for i in self.items],
            "aggregate_score": self.aggregate_score,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
        }


class BaseEnv(ABC):
    """Abstract base environment (Atropos protocol).

    Defines the standard interface for RL environments.
    """

    @abstractmethod
    async def get_next_item(self) -> dict[str, Any]:
        """Get the next task item for evaluation."""
        pass

    @abstractmethod
    async def collect_trajectory(
        self,
        item: dict[str, Any],
        model_output: str,
    ) -> ScoredDataItem:
        """Collect trajectory for an item given model output."""
        pass

    @abstractmethod
    def score(self, item: ScoredDataItem) -> float:
        """Get the score/reward for a scored item."""
        pass

    @abstractmethod
    async def evaluate(
        self,
        items: list[dict[str, Any]],
        outputs: list[str],
    ) -> ScoredDataGroup:
        """Batch evaluation of items and outputs."""
        pass


# ─────────────────────────────────────────────────────────────────────────────
# Gaius Environment Implementation
# ─────────────────────────────────────────────────────────────────────────────


class GaiusEvolutionEnv(BaseEnv):
    """Atropos-compatible environment wrapping EvolutionEngine.

    Provides the standard Atropos interface while delegating all
    actual computation to EvolutionEngine, which runs in gaius-engine.

    This enables:
    1. Internal use by evolution daemon (same interface)
    2. Future external trainer integration (Atropos-compatible)
    3. All RL happening in the engine (GPU-rich remote environment)
    """

    def __init__(
        self,
        agent_id: str,
        domain: str = "",
        max_items_per_batch: int = 10,
    ):
        """Initialize environment.

        Args:
            agent_id: Agent to evolve (leader, critic, etc.)
            domain: Domain context for task generation
            max_items_per_batch: Maximum items per evaluation batch
        """
        self.agent_id = agent_id
        self.domain = domain
        self.max_items = max_items_per_batch

        self._engine = None
        self._item_queue: list[dict[str, Any]] = []
        self._item_counter = 0

    async def _ensure_engine(self):
        """Ensure EvolutionEngine is initialized."""
        if self._engine is None:
            from .engine import get_engine
            self._engine = await get_engine()

    async def get_next_item(self) -> dict[str, Any]:
        """Get the next task item for evaluation.

        Returns:
            Dict with task details (prompt, id, metadata)
        """
        await self._ensure_engine()

        # Refill queue if empty
        if not self._item_queue:
            items = await self._engine.generate_items(self.agent_id, self.max_items)
            self._item_queue = [item.to_dict() for item in items]

        if not self._item_queue:
            # No items available
            self._item_counter += 1
            return {
                "id": f"empty_{self._item_counter}",
                "prompt": "",
                "error": "No evaluation items available",
            }

        return self._item_queue.pop(0)

    async def collect_trajectory(
        self,
        item: dict[str, Any],
        model_output: str,
    ) -> ScoredDataItem:
        """Collect trajectory for an item given model output.

        If model_output is empty, runs the agent to generate output.
        Otherwise, uses the provided output for scoring.

        Args:
            item: Task item dict
            model_output: Model's output (empty to run agent)

        Returns:
            ScoredDataItem with score
        """
        await self._ensure_engine()

        from .engine import TaskItem

        # Convert dict to TaskItem
        task = TaskItem(
            id=item.get("id", "unknown"),
            prompt=item.get("prompt", ""),
            domain=item.get("domain", self.domain),
            category=item.get("category", ""),
            expected_output=item.get("expected_output"),
            context=item.get("context", ""),
        )

        if model_output:
            # Use provided output - just score it
            score, task_completed, _ = await self._engine._score_output(
                model_output, task
            )
            return ScoredDataItem(
                item_id=task.id,
                prompt=task.prompt,
                output=model_output,
                score=score,
                task_completed=task_completed,
            )

        # Run agent to generate output
        from ...models.versioning import get_version_manager

        manager = get_version_manager()
        version = await manager.get_active_version(self.agent_id)

        if version is None:
            return ScoredDataItem(
                item_id=task.id,
                prompt=task.prompt,
                output="",
                score=0.0,
                task_completed=False,
            )

        trajectory = await self._engine.run_trajectory(version.config, task)

        return ScoredDataItem(
            item_id=trajectory.task_id,
            prompt=trajectory.prompt,
            output=trajectory.output,
            score=trajectory.score,
            model=trajectory.model,
            tokens_used=trajectory.tokens_used,
            latency_ms=trajectory.latency_ms,
            task_completed=trajectory.task_completed,
        )

    def score(self, item: ScoredDataItem) -> float:
        """Get the score/reward for a scored item.

        Args:
            item: ScoredDataItem to get score from

        Returns:
            Score as float
        """
        return item.score

    async def evaluate(
        self,
        items: list[dict[str, Any]],
        outputs: list[str],
    ) -> ScoredDataGroup:
        """Batch evaluation of items and outputs.

        Args:
            items: List of task item dicts
            outputs: List of model outputs (parallel to items)

        Returns:
            ScoredDataGroup with all results
        """
        scored_items = []

        for item, output in zip(items, outputs):
            scored = await self.collect_trajectory(item, output)
            scored_items.append(scored)

        import uuid

        return ScoredDataGroup(
            group_id=f"batch_{uuid.uuid4().hex[:8]}",
            items=scored_items,
        )

    async def run_evolution_cycle(self) -> dict[str, Any]:
        """Run a full evolution cycle using the engine.

        This is the primary entry point for internal use.
        External trainers would use get_next_item/collect_trajectory.

        Returns:
            Cycle result dict
        """
        await self._ensure_engine()
        result = await self._engine.run_evolution_cycle(self.agent_id)
        return result.to_dict()


# ─────────────────────────────────────────────────────────────────────────────
# HTTP API Types (for future external trainer integration)
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class EnvRequest:
    """Request to the environment endpoint."""

    action: str  # get_item, collect, evaluate
    agent_id: str
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class EnvResponse:
    """Response from the environment endpoint."""

    success: bool
    data: dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None


class AtroposAPIHandler:
    """HTTP API handler for Atropos compatibility.

    Note: This is for future use when we expose the environment
    via HTTP for external trainers. Currently all evolution runs
    internally in gaius-engine.
    """

    def __init__(self):
        """Initialize handler."""
        self._envs: dict[str, GaiusEvolutionEnv] = {}

    def get_or_create_env(
        self,
        agent_id: str,
        domain: str = "",
    ) -> GaiusEvolutionEnv:
        """Get or create environment for an agent.

        Args:
            agent_id: Agent identifier
            domain: Domain context

        Returns:
            GaiusEvolutionEnv instance
        """
        key = f"{agent_id}:{domain}"
        if key not in self._envs:
            self._envs[key] = GaiusEvolutionEnv(agent_id, domain)
        return self._envs[key]

    async def handle_request(self, request: EnvRequest) -> EnvResponse:
        """Handle an API request.

        Args:
            request: EnvRequest with action and payload

        Returns:
            EnvResponse with result
        """
        try:
            env = self.get_or_create_env(
                request.agent_id,
                request.payload.get("domain", ""),
            )

            if request.action == "get_item":
                item = await env.get_next_item()
                return EnvResponse(success=True, data=item)

            elif request.action == "collect":
                item = request.payload.get("item", {})
                output = request.payload.get("output", "")
                scored = await env.collect_trajectory(item, output)
                return EnvResponse(success=True, data=scored.to_dict())

            elif request.action == "evaluate":
                items = request.payload.get("items", [])
                outputs = request.payload.get("outputs", [])
                group = await env.evaluate(items, outputs)
                return EnvResponse(success=True, data=group.to_dict())

            elif request.action == "run_cycle":
                result = await env.run_evolution_cycle()
                return EnvResponse(success=True, data=result)

            else:
                return EnvResponse(
                    success=False,
                    error=f"Unknown action: {request.action}",
                )

        except Exception as e:
            logger.error(f"API handler error: {e}")
            return EnvResponse(success=False, error=str(e))


# Module-level API handler singleton
_api_handler: Optional[AtroposAPIHandler] = None


def get_api_handler() -> AtroposAPIHandler:
    """Get or create the API handler singleton."""
    global _api_handler
    if _api_handler is None:
        _api_handler = AtroposAPIHandler()
    return _api_handler
