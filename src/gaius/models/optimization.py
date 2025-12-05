"""Agent prompt optimization using local models.

Implements:
- APO (Automatic Prompt Optimization): Mutation-based prompt improvement
- GEPA (Gradient-free Efficient Pareto Agent): Multi-objective Pareto optimization

Key features:
- Pareto frontier tracking for multi-objective optimization
- Local model evaluation (QwQ-32B, Orchestrator-8B)
- Optional frontier model (xAI) for ground-truth calibration
- Integration with agent version control

Usage:
    from gaius.models.optimization import AgentOptimizer, OptimizationStrategy

    optimizer = AgentOptimizer(strategy=OptimizationStrategy.GEPA)

    # Run optimization with multiple objectives
    result = await optimizer.optimize(
        agent_id="leader",
        task_examples=[...],
        objectives=["accuracy", "coherence", "efficiency"],
    )

    # Get Pareto-optimal configs
    pareto_front = result.pareto_front
    print(f"Found {len(pareto_front)} Pareto-optimal configurations")
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable
import asyncio
import json
import random


class OptimizationStrategy(Enum):
    """Optimization strategy to use."""

    APO = "apo"  # Automatic Prompt Optimization (single objective)
    GEPA = "gepa"  # Gradient-free Efficient Pareto Agent (multi-objective)
    HYBRID = "hybrid"  # APO exploration + GEPA selection


class OptimizationObjective(Enum):
    """Objectives for multi-objective optimization."""

    ACCURACY = "accuracy"  # Correctness of outputs
    COHERENCE = "coherence"  # Logical consistency
    RELEVANCE = "relevance"  # Task alignment
    EFFICIENCY = "efficiency"  # Token/latency efficiency
    CREATIVITY = "creativity"  # Novel solutions
    SAFETY = "safety"  # Absence of harmful content
    CONSISTENCY = "consistency"  # Reproducibility across runs


@dataclass
class TaskExample:
    """Example task for optimization evaluation."""

    input_prompt: str
    expected_output: str | None = None
    context: str = ""
    evaluation_criteria: str = ""
    reference_score: float | None = None


@dataclass
class CandidateConfig:
    """A candidate configuration during optimization."""

    system_prompt: str
    temperature: float
    model: str

    # Single-objective scores (APO)
    scores: list[float] = field(default_factory=list)
    avg_score: float = 0.0

    # Multi-objective scores (GEPA)
    objective_scores: dict[OptimizationObjective, float] = field(default_factory=dict)
    is_pareto_optimal: bool = False
    pareto_rank: int = 0  # 0 = Pareto front, 1 = dominated by rank 0, etc.

    # Metadata
    generation_method: str = ""  # "mutation", "crossover", "bootstrap"
    parent_configs: list[str] = field(default_factory=list)
    generation: int = 0  # Which generation this was created in


def is_dominated(a: dict, b: dict) -> bool:
    """Check if solution a is dominated by solution b.

    a is dominated by b if b is at least as good in all objectives
    and strictly better in at least one.
    """
    dominated = False
    for obj in a:
        if obj in b:
            if b[obj] > a[obj]:
                dominated = True
            elif a[obj] > b[obj]:
                return False  # a is better in at least one
    return dominated


def compute_pareto_front(candidates: list[CandidateConfig]) -> list[CandidateConfig]:
    """Compute Pareto-optimal candidates from a population.

    Returns candidates that are not dominated by any other candidate.
    """
    pareto_front = []

    for candidate in candidates:
        is_dominated_by_any = False

        for other in candidates:
            if other is candidate:
                continue

            if is_dominated(candidate.objective_scores, other.objective_scores):
                is_dominated_by_any = True
                break

        if not is_dominated_by_any:
            candidate.is_pareto_optimal = True
            candidate.pareto_rank = 0
            pareto_front.append(candidate)

    return pareto_front


def compute_pareto_ranks(candidates: list[CandidateConfig]) -> None:
    """Assign Pareto ranks to all candidates (non-dominated sorting)."""
    remaining = list(candidates)
    rank = 0

    while remaining:
        front = []
        for candidate in remaining:
            is_dominated_by_any = False
            for other in remaining:
                if other is candidate:
                    continue
                if is_dominated(candidate.objective_scores, other.objective_scores):
                    is_dominated_by_any = True
                    break
            if not is_dominated_by_any:
                candidate.pareto_rank = rank
                candidate.is_pareto_optimal = (rank == 0)
                front.append(candidate)

        for c in front:
            remaining.remove(c)

        rank += 1


def crowding_distance(candidates: list[CandidateConfig], objectives: list[OptimizationObjective]) -> dict[str, float]:
    """Compute crowding distance for diversity preservation.

    Used to select among Pareto-equivalent solutions.
    """
    n = len(candidates)
    if n == 0:
        return {}

    distances = {id(c): 0.0 for c in candidates}

    for obj in objectives:
        # Sort by this objective
        sorted_candidates = sorted(
            candidates,
            key=lambda c: c.objective_scores.get(obj, 0.0)
        )

        # Boundary points get infinite distance
        distances[id(sorted_candidates[0])] = float('inf')
        distances[id(sorted_candidates[-1])] = float('inf')

        # Get objective range
        obj_min = sorted_candidates[0].objective_scores.get(obj, 0.0)
        obj_max = sorted_candidates[-1].objective_scores.get(obj, 0.0)
        obj_range = obj_max - obj_min

        if obj_range == 0:
            continue

        # Compute distances
        for i in range(1, n - 1):
            prev_score = sorted_candidates[i - 1].objective_scores.get(obj, 0.0)
            next_score = sorted_candidates[i + 1].objective_scores.get(obj, 0.0)
            distances[id(sorted_candidates[i])] += (next_score - prev_score) / obj_range

    return distances


@dataclass
class OptimizationResult:
    """Result from an optimization round."""

    # Outcome
    success: bool
    new_version_id: str | None = None
    improvement_percent: float = 0.0

    # Candidates evaluated
    num_candidates: int = 0
    best_candidate_score: float = 0.0
    baseline_score: float = 0.0

    # New config (single best for APO)
    best_config: CandidateConfig | None = None

    # Pareto front (for GEPA multi-objective)
    pareto_front: list[CandidateConfig] = field(default_factory=list)
    pareto_version_ids: list[str] = field(default_factory=list)

    # Objective scores
    objectives_evaluated: list[OptimizationObjective] = field(default_factory=list)
    baseline_objectives: dict[OptimizationObjective, float] = field(default_factory=dict)

    # Metrics
    total_evaluations: int = 0
    total_tokens: int = 0
    latency_ms: int = 0
    generations: int = 0

    # Details
    strategy: OptimizationStrategy = OptimizationStrategy.APO
    iteration: int = 0
    notes: str = ""

    def best_for_objective(self, objective: OptimizationObjective) -> CandidateConfig | None:
        """Get the Pareto-optimal config best for a specific objective."""
        if not self.pareto_front:
            return self.best_config

        best = None
        best_score = -1.0
        for config in self.pareto_front:
            score = config.objective_scores.get(objective, 0.0)
            if score > best_score:
                best_score = score
                best = config

        return best


class AgentOptimizer:
    """Optimizes agent configurations using local models.

    Supports APO (mutation-based) and GEPA (bootstrap-based) strategies,
    both running entirely on local models.

    For parallel execution during overnight runs, set parallel=True to
    distribute evaluations across multiple GPU endpoints.
    """

    def __init__(
        self,
        strategy: OptimizationStrategy = OptimizationStrategy.APO,
        reasoning_model: str = "Qwen/QwQ-32B",
        evaluation_model: str = "Qwen/Qwen3-Coder-30B-A3B-Instruct",
        use_frontier_eval: bool = False,
        parallel: bool = False,
    ):
        """Initialize optimizer.

        Args:
            strategy: Optimization strategy
            reasoning_model: Model for generating prompt variations
            evaluation_model: Model for evaluating candidates
            use_frontier_eval: If True, use xAI for final evaluation
            parallel: If True, use parallel inference across multiple GPUs
        """
        self.strategy = strategy
        self.reasoning_model = reasoning_model
        self.evaluation_model = evaluation_model
        self.use_frontier_eval = use_frontier_eval
        self.parallel = parallel
        self._parallel_client = None

    async def optimize(
        self,
        agent_id: str,
        task_examples: list[TaskExample],
        num_candidates: int = 5,
        num_iterations: int = 3,
        improvement_threshold: float = 0.05,
    ) -> OptimizationResult:
        """Run optimization on an agent.

        Args:
            agent_id: Agent to optimize
            task_examples: Examples to evaluate against
            num_candidates: Candidates per iteration
            num_iterations: Max optimization iterations
            improvement_threshold: Min improvement to accept

        Returns:
            OptimizationResult with new version if improved
        """
        import time
        start = time.perf_counter()

        # Get current config
        from .versioning import get_version_manager, AgentConfig
        manager = get_version_manager()

        current_version = await manager.get_active_version(agent_id)
        if current_version is None:
            return OptimizationResult(
                success=False,
                notes=f"No active version found for agent {agent_id}",
            )

        baseline_config = CandidateConfig(
            system_prompt=current_version.config.system_prompt,
            temperature=current_version.config.temperature,
            model=current_version.config.model,
        )

        # Choose evaluation method based on parallel setting
        evaluate = self._evaluate_config_parallel if self.parallel else self._evaluate_config

        # Evaluate baseline
        baseline_scores = await evaluate(baseline_config, task_examples)
        baseline_config.scores = baseline_scores
        baseline_config.avg_score = sum(baseline_scores) / len(baseline_scores)

        best_config = baseline_config
        total_evals = len(task_examples)
        total_tokens = 0

        # Optimization loop
        for iteration in range(num_iterations):
            # Generate candidates
            if self.strategy == OptimizationStrategy.APO:
                candidates = await self._generate_apo_candidates(
                    best_config, num_candidates
                )
            elif self.strategy == OptimizationStrategy.GEPA:
                candidates = await self._generate_gepa_candidates(
                    best_config, task_examples, num_candidates
                )
            else:  # HYBRID
                apo_candidates = await self._generate_apo_candidates(
                    best_config, num_candidates // 2
                )
                gepa_candidates = await self._generate_gepa_candidates(
                    best_config, task_examples, num_candidates - num_candidates // 2
                )
                candidates = apo_candidates + gepa_candidates

            # Evaluate candidates
            for candidate in candidates:
                scores = await evaluate(candidate, task_examples)
                candidate.scores = scores
                candidate.avg_score = sum(scores) / len(scores)
                total_evals += len(task_examples)

                if candidate.avg_score > best_config.avg_score:
                    best_config = candidate

            # Check if improvement is sufficient
            improvement = (best_config.avg_score - baseline_config.avg_score) / max(
                baseline_config.avg_score, 0.01
            )

            if improvement < improvement_threshold and iteration > 0:
                break

        latency_ms = int((time.perf_counter() - start) * 1000)

        # Calculate final improvement
        final_improvement = (
            (best_config.avg_score - baseline_config.avg_score)
            / max(baseline_config.avg_score, 0.01)
            * 100
        )

        # Save new version if improved
        new_version_id = None
        if best_config != baseline_config and final_improvement > 0:
            # Optional frontier evaluation for ground truth
            if self.use_frontier_eval:
                frontier_score = await self._frontier_evaluate(best_config, task_examples)
                best_config.avg_score = (best_config.avg_score + frontier_score) / 2

            new_config = AgentConfig(
                system_prompt=best_config.system_prompt,
                temperature=best_config.temperature,
                model=best_config.model,
                description=f"Optimized via {self.strategy.value}",
                tags=["optimized", self.strategy.value],
            )

            version = await manager.save_version(
                agent_id=agent_id,
                config=new_config,
                metrics={"optimization_score": best_config.avg_score},
                parent_version=current_version.version_id,
                change_notes=f"{self.strategy.value} optimization: {final_improvement:.1f}% improvement",
                set_active=True,
            )
            new_version_id = version.version_id

        return OptimizationResult(
            success=new_version_id is not None,
            new_version_id=new_version_id,
            improvement_percent=final_improvement,
            num_candidates=num_candidates * num_iterations,
            best_candidate_score=best_config.avg_score,
            baseline_score=baseline_config.avg_score,
            best_config=best_config if new_version_id else None,
            total_evaluations=total_evals,
            total_tokens=total_tokens,
            latency_ms=latency_ms,
            strategy=self.strategy,
            iteration=iteration + 1,
        )

    async def _generate_apo_candidates(
        self,
        base_config: CandidateConfig,
        num_candidates: int,
    ) -> list[CandidateConfig]:
        """Generate candidates using APO (mutation-based).

        Uses local reasoning model to propose prompt improvements.
        """
        from ..inference import get_client, Message

        candidates = []
        client = get_client()

        # Generate prompt variations
        for i in range(num_candidates):
            mutation_type = random.choice([
                "clarify_instructions",
                "add_examples",
                "restructure",
                "add_constraints",
                "simplify",
            ])

            prompt = f"""You are optimizing an AI agent's system prompt.

Current system prompt:
```
{base_config.system_prompt}
```

Generate an improved version using this mutation strategy: {mutation_type}

Requirements:
1. Keep the core purpose and capabilities
2. Make the prompt more effective for the agent's task
3. Be concise but complete

Output ONLY the new system prompt, nothing else."""

            result = await client.complete(
                [Message(role="user", content=prompt)],
                temperature=0.8,  # Higher for diversity
                max_tokens=2048,
            )

            new_prompt = result.content.strip()
            if new_prompt.startswith("```"):
                new_prompt = new_prompt.split("```")[1].strip()

            # Also try temperature variations
            temp_variation = base_config.temperature + random.uniform(-0.2, 0.2)
            temp_variation = max(0.1, min(1.0, temp_variation))

            candidates.append(CandidateConfig(
                system_prompt=new_prompt,
                temperature=temp_variation,
                model=base_config.model,
                generation_method="apo_mutation",
                parent_configs=[f"mutation_{mutation_type}"],
            ))

        return candidates

    async def _generate_gepa_candidates(
        self,
        base_config: CandidateConfig,
        examples: list[TaskExample],
        num_candidates: int,
    ) -> list[CandidateConfig]:
        """Generate candidates using GEPA (bootstrap-based).

        Learns from examples to construct better prompts.
        """
        from ..inference import get_client, Message

        candidates = []
        client = get_client()

        # Bootstrap: analyze successful patterns from examples
        example_analysis = []
        for ex in examples[:5]:  # Analyze up to 5 examples
            if ex.expected_output:
                example_analysis.append(
                    f"Input: {ex.input_prompt[:200]}...\n"
                    f"Expected: {ex.expected_output[:200]}..."
                )

        examples_text = "\n\n".join(example_analysis)

        for i in range(num_candidates):
            strategy = random.choice([
                "instruction_induction",
                "demonstration_bootstrap",
                "criteria_extraction",
            ])

            if strategy == "instruction_induction":
                prompt = f"""Analyze these input-output examples and induce the optimal instructions:

{examples_text}

Current system prompt:
```
{base_config.system_prompt}
```

Create an improved system prompt that better captures the patterns in these examples.
Output ONLY the new system prompt."""

            elif strategy == "demonstration_bootstrap":
                prompt = f"""You are bootstrapping a better prompt from demonstrations.

Examples of desired behavior:
{examples_text}

Current system prompt:
```
{base_config.system_prompt}
```

Rewrite the system prompt to better guide the agent toward outputs like the examples.
Output ONLY the new system prompt."""

            else:  # criteria_extraction
                prompt = f"""Extract the implicit quality criteria from these examples:

{examples_text}

Current system prompt:
```
{base_config.system_prompt}
```

Add explicit criteria/guidelines to the system prompt based on patterns in the examples.
Output ONLY the new system prompt."""

            result = await client.complete(
                [Message(role="user", content=prompt)],
                temperature=0.7,
                max_tokens=2048,
            )

            new_prompt = result.content.strip()
            if new_prompt.startswith("```"):
                new_prompt = new_prompt.split("```")[1].strip()

            candidates.append(CandidateConfig(
                system_prompt=new_prompt,
                temperature=base_config.temperature,
                model=base_config.model,
                generation_method="gepa_bootstrap",
                parent_configs=[f"bootstrap_{strategy}"],
            ))

        return candidates

    async def _evaluate_config(
        self,
        config: CandidateConfig,
        examples: list[TaskExample],
    ) -> list[float]:
        """Evaluate a config against examples using local model."""
        from ..inference import get_client, Message

        client = get_client()
        scores = []

        for example in examples:
            # Generate output with candidate config
            result = await client.complete(
                [
                    Message(role="system", content=config.system_prompt),
                    Message(role="user", content=example.input_prompt),
                ],
                temperature=config.temperature,
                max_tokens=1024,
            )
            output = result.content

            # Evaluate output
            if example.expected_output:
                # Compare to expected output
                eval_prompt = f"""Rate this output on a scale of 0-1.

Task: {example.input_prompt[:500]}

Expected output: {example.expected_output[:500]}

Actual output: {output[:500]}

{f"Evaluation criteria: {example.evaluation_criteria}" if example.evaluation_criteria else ""}

Respond with ONLY a number between 0 and 1."""

                eval_result = await client.complete(
                    [Message(role="user", content=eval_prompt)],
                    temperature=0.1,
                    max_tokens=10,
                )

                try:
                    score = float(eval_result.content.strip())
                    score = max(0.0, min(1.0, score))
                except ValueError:
                    score = 0.5

            else:
                # Self-evaluate without reference
                eval_prompt = f"""Rate the quality of this output on a scale of 0-1.

Task: {example.input_prompt[:500]}

Output: {output[:500]}

{f"Evaluation criteria: {example.evaluation_criteria}" if example.evaluation_criteria else "Consider: accuracy, completeness, clarity, relevance."}

Respond with ONLY a number between 0 and 1."""

                eval_result = await client.complete(
                    [Message(role="user", content=eval_prompt)],
                    temperature=0.1,
                    max_tokens=10,
                )

                try:
                    score = float(eval_result.content.strip())
                    score = max(0.0, min(1.0, score))
                except ValueError:
                    score = 0.5

            scores.append(score)

        return scores

    async def _evaluate_config_parallel(
        self,
        config: CandidateConfig,
        examples: list[TaskExample],
    ) -> list[float]:
        """Evaluate a config in parallel across multiple endpoints.

        Uses the parallel inference client to distribute evaluations
        across all available GPU endpoints for ~6x speedup.
        """
        from ..inference.parallel import get_parallel_client

        client = get_parallel_client()
        if client.num_endpoints == 0:
            # Fall back to sequential
            return await self._evaluate_config(config, examples)

        # Phase 1: Generate outputs for all examples in parallel
        generate_messages = []
        for example in examples:
            generate_messages.append([
                {"role": "system", "content": config.system_prompt},
                {"role": "user", "content": example.input_prompt},
            ])

        generate_results = await client.parallel_complete(
            generate_messages,
            temperature=config.temperature,
            max_tokens=1024,
        )

        # Phase 2: Evaluate all outputs in parallel
        eval_messages = []
        for i, (example, gen_result) in enumerate(zip(examples, generate_results)):
            if not gen_result.success:
                # Will use 0.5 as default score
                eval_messages.append([{"role": "user", "content": "Rate: 0.5"}])
                continue

            output = gen_result.content

            if example.expected_output:
                eval_prompt = f"""Rate this output on a scale of 0-1.

Task: {example.input_prompt[:500]}

Expected output: {example.expected_output[:500]}

Actual output: {output[:500]}

{f"Evaluation criteria: {example.evaluation_criteria}" if example.evaluation_criteria else ""}

Respond with ONLY a number between 0 and 1."""
            else:
                eval_prompt = f"""Rate the quality of this output on a scale of 0-1.

Task: {example.input_prompt[:500]}

Output: {output[:500]}

{f"Evaluation criteria: {example.evaluation_criteria}" if example.evaluation_criteria else "Consider: accuracy, completeness, clarity, relevance."}

Respond with ONLY a number between 0 and 1."""

            eval_messages.append([{"role": "user", "content": eval_prompt}])

        eval_results = await client.parallel_complete(
            eval_messages,
            temperature=0.1,
            max_tokens=10,
        )

        # Parse scores
        scores = []
        for eval_result in eval_results:
            if eval_result.success:
                try:
                    score = float(eval_result.content.strip())
                    score = max(0.0, min(1.0, score))
                except ValueError:
                    score = 0.5
            else:
                score = 0.5
            scores.append(score)

        return scores

    async def _frontier_evaluate(
        self,
        config: CandidateConfig,
        examples: list[TaskExample],
    ) -> float:
        """Get ground-truth evaluation from frontier model (xAI)."""
        from .evaluation import get_evaluator, EvaluationDimension

        try:
            evaluator = get_evaluator()
        except ValueError:
            # No xAI API key, skip
            return config.avg_score

        from ..inference import get_client, Message
        client = get_client()

        scores = []
        for example in examples[:3]:  # Limit frontier calls
            # Generate output
            result = await client.complete(
                [
                    Message(role="system", content=config.system_prompt),
                    Message(role="user", content=example.input_prompt),
                ],
                temperature=config.temperature,
                max_tokens=1024,
            )

            # Evaluate with frontier
            eval_result = await evaluator.evaluate(
                agent_output=result.content,
                task_prompt=example.input_prompt,
                context=example.context,
                dimensions=[
                    EvaluationDimension.ACCURACY,
                    EvaluationDimension.RELEVANCE,
                    EvaluationDimension.COMPLETENESS,
                ],
            )
            scores.append(eval_result.overall_score)

        return sum(scores) / len(scores) if scores else config.avg_score


class ScheduledOptimizer:
    """Runs periodic optimization on agents."""

    def __init__(
        self,
        optimizer: AgentOptimizer | None = None,
        interval_hours: int = 24,
    ):
        """Initialize scheduled optimizer.

        Args:
            optimizer: AgentOptimizer instance
            interval_hours: Hours between optimization runs
        """
        self.optimizer = optimizer or AgentOptimizer()
        self.interval_hours = interval_hours
        self._running = False
        self._task = None

    async def start(self, agent_ids: list[str], examples_provider: Callable):
        """Start periodic optimization.

        Args:
            agent_ids: Agents to optimize
            examples_provider: Async function that returns task examples
        """
        self._running = True

        while self._running:
            for agent_id in agent_ids:
                try:
                    examples = await examples_provider(agent_id)
                    if examples:
                        result = await self.optimizer.optimize(
                            agent_id=agent_id,
                            task_examples=examples,
                        )
                        if result.success:
                            print(
                                f"Optimized {agent_id}: "
                                f"{result.improvement_percent:.1f}% improvement"
                            )
                except Exception as e:
                    print(f"Optimization failed for {agent_id}: {e}")

            # Wait for next interval
            await asyncio.sleep(self.interval_hours * 3600)

    def stop(self):
        """Stop periodic optimization."""
        self._running = False


# ═══════════════════════════════════════════════════════════════════════════════
# Module-level API
# ═══════════════════════════════════════════════════════════════════════════════

_optimizer: AgentOptimizer | None = None
_parallel_optimizer: AgentOptimizer | None = None


def get_optimizer(
    strategy: OptimizationStrategy = OptimizationStrategy.APO,
    parallel: bool = False,
) -> AgentOptimizer:
    """Get or create the agent optimizer singleton.

    Args:
        strategy: Optimization strategy (APO, GEPA, or HYBRID)
        parallel: If True, use parallel inference across multiple GPUs

    Returns:
        AgentOptimizer instance (creates new one if parallel mode changes)
    """
    global _optimizer, _parallel_optimizer

    if parallel:
        if _parallel_optimizer is None:
            _parallel_optimizer = AgentOptimizer(strategy=strategy, parallel=True)
        return _parallel_optimizer
    else:
        if _optimizer is None:
            _optimizer = AgentOptimizer(strategy=strategy, parallel=False)
        return _optimizer


async def optimize_agent(
    agent_id: str,
    task_examples: list[TaskExample],
    strategy: OptimizationStrategy = OptimizationStrategy.APO,
    parallel: bool = False,
) -> OptimizationResult:
    """Convenience function to optimize an agent."""
    optimizer = get_optimizer(strategy, parallel=parallel)
    return await optimizer.optimize(agent_id, task_examples)
