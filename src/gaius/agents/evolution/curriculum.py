"""Curriculum agent for Agent0-style task generation.

Proposes increasingly challenging tasks at the edge of
the executor agent's capability, enabling continuous improvement.

Key insight from Agent0: Target ~70% success rate
(zone of proximal development) for optimal learning.
"""

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional
from gaius.core.budgets import REASONING_MAX_TOKENS

logger = logging.getLogger(__name__)


class TaskCategory(Enum):
    """Categories of evolution tasks."""

    REASONING = "reasoning"  # Logic, analysis, synthesis
    TOOL_USE = "tool_use"  # Using MCP tools effectively
    SYNTHESIS = "synthesis"  # Combining multiple sources
    CREATIVITY = "creativity"  # Novel connections
    ACCURACY = "accuracy"  # Factual correctness


@dataclass
class EvolutionTask:
    """A task for agent evolution.

    Attributes:
        id: Unique identifier
        description: Human-readable description
        category: Task category
        difficulty: Difficulty level (0.0-1.0)
        input_prompt: The prompt to give the agent
        evaluation_criteria: How to evaluate success
        available_tools: Tools the agent can use
        expected_capabilities: What agent should demonstrate
        metadata: Additional metadata
    """

    id: str
    description: str
    category: TaskCategory
    difficulty: float
    input_prompt: str
    evaluation_criteria: str
    available_tools: list[str] = field(default_factory=list)
    expected_capabilities: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)

    @classmethod
    def create(
        cls,
        description: str,
        category: TaskCategory | str,
        difficulty: float,
        input_prompt: str,
        evaluation_criteria: str,
        **kwargs,
    ) -> "EvolutionTask":
        """Create a new evolution task.

        Args:
            description: Human-readable description
            category: Task category
            difficulty: Difficulty 0.0-1.0
            input_prompt: Prompt for agent
            evaluation_criteria: Success criteria
            **kwargs: Additional fields
        """
        if isinstance(category, str):
            category = TaskCategory(category)

        return cls(
            id=str(uuid.uuid4()),
            description=description,
            category=category,
            difficulty=max(0.0, min(1.0, difficulty)),
            input_prompt=input_prompt,
            evaluation_criteria=evaluation_criteria,
            **kwargs,
        )


@dataclass
class TaskResult:
    """Result from executing an evolution task."""

    task_id: str
    success: bool
    score: float  # 0.0-1.0
    output: str
    feedback: str = ""
    dimension_scores: dict = field(default_factory=dict)
    tokens_used: int = 0
    latency_ms: int = 0


class CurriculumAgent:
    """Agent0-style curriculum agent that proposes challenging tasks.

    Analyzes executor's recent performance and proposes tasks
    at the edge of its capability (targeting ~70% success rate).

    This creates a symbiotic competition where:
    - Executor improvement pressures curriculum to create harder tasks
    - Harder tasks push executor to improve further
    """

    # Target success rate for optimal learning
    TARGET_SUCCESS_RATE = 0.7

    # Difficulty adjustment step
    DIFFICULTY_STEP = 0.1

    def __init__(self):
        """Initialize curriculum agent."""
        self._inference_client = None

    async def _get_inference_client(self):
        """Get or create the engine inference client (gRPC).

        Was the raw GrpcEngineClient, which has no .complete(messages) — every
        LLM task generation silently fell back to a default task. The
        EngineInferenceClient exposes the complete() this class calls.
        """
        if self._inference_client is None:
            from gaius.client.engine_client import get_engine_client
            self._inference_client = await get_engine_client()
        return self._inference_client

    async def propose_task(
        self,
        executor_id: str,
        recent_results: list[TaskResult],
        focus_category: TaskCategory | None = None,
    ) -> EvolutionTask:
        """Propose a task at the edge of executor's capability.

        Args:
            executor_id: ID of target executor agent
            recent_results: Recent task results for analysis
            focus_category: Optional category to focus on

        Returns:
            EvolutionTask tailored to executor's needs
        """
        # Analyze recent performance
        weak_categories = self._identify_weaknesses(recent_results)
        target_difficulty = self._compute_target_difficulty(recent_results)

        # Select category
        if focus_category:
            category = focus_category
        elif weak_categories:
            category = weak_categories[0]
        else:
            category = TaskCategory.REASONING

        # Generate task via LLM
        task = await self._generate_task(
            executor_id=executor_id,
            category=category,
            target_difficulty=target_difficulty,
            weak_areas=weak_categories,
        )

        logger.info(
            f"Proposed task for {executor_id}: "
            f"{category.value} at difficulty {target_difficulty:.2f}"
        )

        return task

    async def propose_curriculum(
        self,
        executor_id: str,
        num_tasks: int = 5,
        recent_results: list[TaskResult] | None = None,
    ) -> list[EvolutionTask]:
        """Generate a progressive curriculum of tasks.

        Creates a sequence of tasks with increasing difficulty,
        covering multiple categories.

        Args:
            executor_id: ID of target executor agent
            num_tasks: Number of tasks to generate
            recent_results: Recent results for calibration

        Returns:
            List of EvolutionTasks in increasing difficulty
        """
        results = recent_results or []
        tasks = []

        base_difficulty = self._compute_target_difficulty(results)

        # Generate tasks across categories
        categories = list(TaskCategory)
        for i in range(num_tasks):
            # Vary category
            category = categories[i % len(categories)]

            # Gradually increase difficulty
            difficulty = min(1.0, base_difficulty + (i * 0.05))

            task = await self._generate_task(
                executor_id=executor_id,
                category=category,
                target_difficulty=difficulty,
            )
            tasks.append(task)

        return tasks

    def _identify_weaknesses(
        self,
        results: list[TaskResult],
    ) -> list[TaskCategory]:
        """Identify weak categories from results.

        Args:
            results: Recent task results

        Returns:
            Categories sorted by weakness (worst first)
        """
        if not results:
            return []

        # Group scores by category
        category_scores: dict[TaskCategory, list[float]] = {}

        for result in results:
            # Try to get category from metadata
            cat_str = result.dimension_scores.get("category", "reasoning")
            try:
                category = TaskCategory(cat_str)
            except ValueError:
                category = TaskCategory.REASONING

            if category not in category_scores:
                category_scores[category] = []
            category_scores[category].append(result.score)

        # Compute average per category
        category_avgs = {
            cat: sum(scores) / len(scores)
            for cat, scores in category_scores.items()
        }

        # Sort by score (ascending = weakest first)
        sorted_cats = sorted(
            category_avgs.keys(),
            key=lambda c: category_avgs[c],
        )

        return sorted_cats

    def _compute_target_difficulty(
        self,
        results: list[TaskResult],
    ) -> float:
        """Compute target difficulty for next task.

        Targets ~70% success rate (zone of proximal development).

        Args:
            results: Recent task results

        Returns:
            Target difficulty (0.0-1.0)
        """
        if not results:
            return 0.3  # Start moderate

        # Compute recent success rate
        recent = results[-10:]  # Last 10 tasks
        success_count = sum(1 for r in recent if r.success)
        success_rate = success_count / len(recent)

        # Get current average difficulty
        difficulties = [
            r.dimension_scores.get("difficulty", 0.5)
            for r in recent
        ]
        current_difficulty = sum(difficulties) / len(difficulties)

        # Adjust difficulty based on success rate
        if success_rate > 0.8:
            # Too easy - increase difficulty
            return min(1.0, current_difficulty + self.DIFFICULTY_STEP)
        elif success_rate < 0.5:
            # Too hard - decrease difficulty
            return max(0.1, current_difficulty - self.DIFFICULTY_STEP)
        else:
            # In target zone
            return current_difficulty

    async def _generate_task(
        self,
        executor_id: str,
        category: TaskCategory,
        target_difficulty: float,
        weak_areas: list[TaskCategory] | None = None,
    ) -> EvolutionTask:
        """Generate a task using LLM.

        Args:
            executor_id: Target executor
            category: Task category
            target_difficulty: Target difficulty
            weak_areas: Areas to potentially focus on

        Returns:
            Generated EvolutionTask
        """
        try:
            client = await self._get_inference_client()

            # Build generation prompt
            prompt = self._build_generation_prompt(
                executor_id=executor_id,
                category=category,
                target_difficulty=target_difficulty,
                weak_areas=weak_areas,
            )

            from gaius.client.engine_client import Message

            result = await client.complete(
                [Message(role="user", content=prompt)],
                temperature=0.8,  # Creative
                max_tokens=REASONING_MAX_TOKENS,
            )

            # Parse response into task
            return self._parse_task_response(
                response=result.content,
                category=category,
                difficulty=target_difficulty,
            )

        except Exception as e:
            logger.warning(f"Failed to generate task via LLM: {e}")
            # Return a default task
            return self._create_default_task(category, target_difficulty)

    def _build_generation_prompt(
        self,
        executor_id: str,
        category: TaskCategory,
        target_difficulty: float,
        weak_areas: list[TaskCategory] | None = None,
    ) -> str:
        """Build prompt for task generation."""
        weak_str = ""
        if weak_areas:
            weak_str = f"\nWeak areas to address: {', '.join(c.value for c in weak_areas)}"

        return f"""Generate a challenging task for an AI agent to improve its {category.value} capabilities.

Target difficulty: {target_difficulty:.1f}/1.0 (where 1.0 is very challenging)
Agent role: {executor_id}{weak_str}

Generate a task that:
1. Tests {category.value} abilities at difficulty {target_difficulty:.1f}
2. Has clear success criteria
3. Can be evaluated objectively

Respond in this exact format:
DESCRIPTION: [one-line description]
PROMPT: [the actual prompt to give the agent]
CRITERIA: [how to evaluate success]
CAPABILITIES: [comma-separated list of capabilities being tested]"""

    def _parse_task_response(
        self,
        response: str,
        category: TaskCategory,
        difficulty: float,
    ) -> EvolutionTask:
        """Parse LLM response into EvolutionTask."""
        lines = response.strip().split("\n")

        description = ""
        prompt = ""
        criteria = ""
        capabilities = []

        for line in lines:
            line = line.strip()
            if line.startswith("DESCRIPTION:"):
                description = line[12:].strip()
            elif line.startswith("PROMPT:"):
                prompt = line[7:].strip()
            elif line.startswith("CRITERIA:"):
                criteria = line[9:].strip()
            elif line.startswith("CAPABILITIES:"):
                caps = line[13:].strip()
                capabilities = [c.strip() for c in caps.split(",")]

        # Fallback if parsing failed
        if not prompt:
            prompt = response[:500]
        if not description:
            description = f"{category.value} task at difficulty {difficulty:.1f}"
        if not criteria:
            criteria = "Evaluate based on accuracy, completeness, and clarity"

        return EvolutionTask.create(
            description=description,
            category=category,
            difficulty=difficulty,
            input_prompt=prompt,
            evaluation_criteria=criteria,
            expected_capabilities=capabilities,
        )

    def _create_default_task(
        self,
        category: TaskCategory,
        difficulty: float,
    ) -> EvolutionTask:
        """Create a default task when LLM generation fails."""
        prompts = {
            TaskCategory.REASONING: "Analyze the trade-offs between consistency and availability in distributed systems.",
            TaskCategory.TOOL_USE: "Search the knowledge base for relevant information and synthesize a response.",
            TaskCategory.SYNTHESIS: "Combine insights from multiple domains to identify novel patterns.",
            TaskCategory.CREATIVITY: "Propose an unconventional solution to a complex problem.",
            TaskCategory.ACCURACY: "Provide a precise, factual response with citations.",
        }

        return EvolutionTask.create(
            description=f"Default {category.value} task",
            category=category,
            difficulty=difficulty,
            input_prompt=prompts.get(category, prompts[TaskCategory.REASONING]),
            evaluation_criteria="Evaluate based on accuracy, completeness, and clarity",
        )


# Module-level singleton
_curriculum_agent: CurriculumAgent | None = None


def get_curriculum_agent() -> CurriculumAgent:
    """Get or create curriculum agent singleton."""
    global _curriculum_agent
    if _curriculum_agent is None:
        _curriculum_agent = CurriculumAgent()
    return _curriculum_agent
