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

    # Technique-aware objectives (for full-stack optimization)
    LATENCY = "latency"  # Response time (lower is better, normalized)
    TOKEN_EFFICIENCY = "token_efficiency"  # Quality per token
    GATE_PASS_RATE = "gate_pass_rate"  # Validation gate success rate
    VERBALIZATION_RATIO = "verbalization_ratio"  # Ontology verbalization %


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

    # optillm technique support (for full-stack optimization)
    technique: str = ""  # optillm technique (cot_reflection, bon, moa, etc.)
    technique_params: dict[str, Any] = field(default_factory=dict)  # e.g., {"n": 5} for BON

    # Single-objective scores (APO)
    scores: list[float] = field(default_factory=list)
    avg_score: float = 0.0

    # Multi-objective scores (GEPA)
    objective_scores: dict[OptimizationObjective, float] = field(default_factory=dict)
    is_pareto_optimal: bool = False
    pareto_rank: int = 0  # 0 = Pareto front, 1 = dominated by rank 0, etc.

    # Performance metrics (for Pareto optimization)
    latency_ms: int = 0
    tokens_used: int = 0
    token_efficiency: float = 0.0  # quality / tokens

    # Metadata
    generation_method: str = ""  # "mutation", "crossover", "bootstrap", "technique"
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


def crowding_distance(candidates: list[CandidateConfig], objectives: list[OptimizationObjective]) -> dict[int, float]:
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

    def best_for_objective(self, objective: OptimizationObjective) -> CandidateConfig:
        """Get the Pareto-optimal config best for a specific objective.

        Raises:
            RuntimeError: If no config available for the objective
        """
        if not self.pareto_front:
            if self.best_config is None:
                raise RuntimeError(
                    f"No config available for objective {objective.name}\n"
                    f"  Guru Meditation: #OPT.00000001.NOCONFIG"
                )
            return self.best_config

        best = None
        best_score = -1.0
        for config in self.pareto_front:
            score = config.objective_scores.get(objective, 0.0)
            if score > best_score:
                best_score = score
                best = config

        if best is None:
            raise RuntimeError(
                f"No config in pareto_front for objective {objective.name}\n"
                f"  Guru Meditation: #OPT.00000002.NOPARETOCONFIG"
            )
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

    async def optimize_with_techniques(
        self,
        agent_id: str,
        task_examples: list[TaskExample],
        num_iterations: int = 5,
        candidates_per_iter: int = 6,
        objectives: list[OptimizationObjective] | None = None,
    ) -> OptimizationResult:
        """Full-stack GEPA optimization with joint technique search using Pareto.

        Jointly optimizes:
        - System prompt (via GEPA bootstrap)
        - Temperature
        - optillm technique (cot_reflection, bon, moa, etc.)
        - Technique parameters (e.g., n=5 for BON)

        Uses Pareto multi-objective optimization considering:
        - Accuracy (primary quality metric)
        - Latency (lower is better)
        - Token efficiency (quality per ktok)

        Args:
            agent_id: Agent to optimize
            task_examples: Examples to evaluate against
            num_iterations: Number of optimization iterations
            candidates_per_iter: Candidates generated per iteration
            objectives: Objectives to optimize (default: accuracy, latency, token_efficiency)

        Returns:
            OptimizationResult with Pareto front of non-dominated configs
        """
        import time
        start = time.perf_counter()

        if objectives is None:
            objectives = [
                OptimizationObjective.ACCURACY,
                OptimizationObjective.LATENCY,
                OptimizationObjective.TOKEN_EFFICIENCY,
            ]

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
            technique=current_version.config.optillm_technique or "",
            technique_params=current_version.config.technique_params or {},
        )

        # Evaluate baseline
        baseline_scores = await self._evaluate_config(baseline_config, task_examples)
        baseline_config.scores = baseline_scores
        baseline_config.avg_score = sum(baseline_scores) / len(baseline_scores) if baseline_scores else 0.0

        # Populate objective scores for baseline
        baseline_config.objective_scores = {
            OptimizationObjective.ACCURACY: baseline_config.avg_score,
            OptimizationObjective.LATENCY: 1.0 - min(baseline_config.latency_ms / 60000, 1.0),
            OptimizationObjective.TOKEN_EFFICIENCY: min(baseline_config.token_efficiency / 10.0, 1.0),
        }

        all_candidates = [baseline_config]
        best = baseline_config
        total_evals = len(task_examples)

        for iteration in range(num_iterations):
            # Generate diverse candidates (2 each: prompt, technique, hybrid)
            prompt_candidates = await self._generate_gepa_candidates(
                best, task_examples, max(1, candidates_per_iter // 3)
            )
            technique_candidates = await self._generate_technique_candidates(
                best, max(1, candidates_per_iter // 3)
            )
            hybrid_candidates = await self._generate_hybrid_candidates(
                best, task_examples, candidates_per_iter - len(prompt_candidates) - len(technique_candidates)
            )

            new_candidates = prompt_candidates + technique_candidates + hybrid_candidates

            # Evaluate all candidates
            for candidate in new_candidates:
                scores = await self._evaluate_config(candidate, task_examples)
                candidate.scores = scores
                candidate.avg_score = sum(scores) / len(scores) if scores else 0.0
                total_evals += len(task_examples)

                # Populate objective scores for Pareto
                candidate.objective_scores = {
                    OptimizationObjective.ACCURACY: candidate.avg_score,
                    OptimizationObjective.LATENCY: 1.0 - min(candidate.latency_ms / 60000, 1.0),
                    OptimizationObjective.TOKEN_EFFICIENCY: min(candidate.token_efficiency / 10.0, 1.0),
                }

            all_candidates.extend(new_candidates)

            # Compute Pareto front and ranks
            pareto_front = compute_pareto_front(all_candidates)
            compute_pareto_ranks(all_candidates)

            # Select best from Pareto front for next iteration
            # Prefer accuracy when ranks are equal
            if pareto_front:
                best = max(
                    pareto_front,
                    key=lambda c: c.objective_scores.get(OptimizationObjective.ACCURACY, 0.0)
                )

        latency_ms = int((time.perf_counter() - start) * 1000)

        # Final Pareto front
        pareto_front = compute_pareto_front(all_candidates)

        # Calculate improvement from baseline
        best_accuracy = max(
            (c.objective_scores.get(OptimizationObjective.ACCURACY, 0.0) for c in pareto_front),
            default=0.0
        )
        baseline_accuracy = baseline_config.objective_scores.get(OptimizationObjective.ACCURACY, 0.0)
        improvement = ((best_accuracy - baseline_accuracy) / max(baseline_accuracy, 0.01)) * 100

        return OptimizationResult(
            success=len(pareto_front) > 0,
            improvement_percent=improvement,
            num_candidates=len(all_candidates),
            best_candidate_score=best_accuracy,
            baseline_score=baseline_accuracy,
            best_config=best,
            pareto_front=pareto_front,
            total_evaluations=total_evals,
            latency_ms=latency_ms,
            strategy=OptimizationStrategy.GEPA,
            generations=num_iterations,
            objectives_evaluated=objectives,
            baseline_objectives=baseline_config.objective_scores,
            notes=f"Full-stack Pareto optimization: {len(pareto_front)} non-dominated solutions",
        )

    async def _generate_apo_candidates(
        self,
        base_config: CandidateConfig,
        num_candidates: int,
    ) -> list[CandidateConfig]:
        """Generate candidates using APO (mutation-based).

        Uses local reasoning model to propose prompt improvements.
        """
        from gaius.client import get_grpc_client

        candidates = []
        client = await get_grpc_client()

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

            result = await client.call(
                service="Scheduler",
                action="complete",
                params={
                    "prompt": prompt,
                    "agent": "fast",
                    "temperature": 0.8,  # Higher for diversity
                    "max_tokens": 2048,
                },
            )

            new_prompt = result.get("content", "").strip()
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
        from gaius.client import get_grpc_client

        candidates = []
        client = await get_grpc_client()

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

            result = await client.call(
                service="Scheduler",
                action="complete",
                params={
                    "prompt": prompt,
                    "agent": "fast",
                    "temperature": 0.7,
                    "max_tokens": 2048,
                },
            )

            new_prompt = result.get("content", "").strip()
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

    # Technique configurations for optillm
    TECHNIQUE_CONFIGS: list[tuple[str, dict[str, Any]]] = [
        ("", {}),                      # Passthrough (no technique)
        ("cot_reflection", {}),        # Chain-of-Thought with reflection
        ("bon", {"n": 3}),             # Best of 3
        ("bon", {"n": 5}),             # Best of 5
        ("moa", {}),                   # Mixture of Agents
        ("self_consistency", {}),      # Self-consistency
        ("plansearch", {}),            # Plan-based search
        ("re2", {}),                   # Re-reading
    ]

    async def _generate_technique_candidates(
        self,
        base_config: CandidateConfig,
        num_candidates: int,
    ) -> list[CandidateConfig]:
        """Generate candidates exploring technique space.

        Creates variations by changing the optillm technique while keeping
        the prompt relatively stable. This enables full-stack optimization
        that jointly explores prompt AND inference strategy.
        """
        candidates = []

        for i in range(num_candidates):
            tech, params = random.choice(self.TECHNIQUE_CONFIGS)

            # Small temperature variation
            temp_variation = base_config.temperature + random.uniform(-0.1, 0.1)
            temp_variation = max(0.1, min(1.0, temp_variation))

            candidates.append(CandidateConfig(
                system_prompt=base_config.system_prompt,
                temperature=temp_variation,
                model=base_config.model,
                technique=tech,
                technique_params=params.copy(),
                generation_method="technique_variation",
                parent_configs=[f"technique_{tech or 'passthrough'}"],
            ))

        return candidates

    async def _generate_hybrid_candidates(
        self,
        base_config: CandidateConfig,
        examples: list[TaskExample],
        num_candidates: int,
    ) -> list[CandidateConfig]:
        """Generate hybrid candidates that vary both prompt AND technique.

        Combines GEPA prompt optimization with technique exploration
        for true full-stack optimization.
        """
        candidates = []

        # Generate some prompt variations
        prompt_candidates = await self._generate_gepa_candidates(
            base_config, examples, max(1, num_candidates // 2)
        )

        # Apply random techniques to each prompt variant
        for prompt_candidate in prompt_candidates:
            tech, params = random.choice(self.TECHNIQUE_CONFIGS)

            candidates.append(CandidateConfig(
                system_prompt=prompt_candidate.system_prompt,
                temperature=prompt_candidate.temperature,
                model=prompt_candidate.model,
                technique=tech,
                technique_params=params.copy(),
                generation_method="hybrid_prompt_technique",
                parent_configs=[
                    prompt_candidate.generation_method,
                    f"technique_{tech or 'passthrough'}",
                ],
            ))

        # Fill remaining with pure technique variations
        while len(candidates) < num_candidates:
            tech, params = random.choice(self.TECHNIQUE_CONFIGS)
            candidates.append(CandidateConfig(
                system_prompt=base_config.system_prompt,
                temperature=base_config.temperature + random.uniform(-0.1, 0.1),
                model=base_config.model,
                technique=tech,
                technique_params=params.copy(),
                generation_method="hybrid_technique_fill",
                parent_configs=[f"technique_{tech or 'passthrough'}"],
            ))

        return candidates[:num_candidates]

    async def _evaluate_config(
        self,
        config: CandidateConfig,
        examples: list[TaskExample],
    ) -> list[float]:
        """Evaluate a config against examples using engine via AgentRunner.

        Uses the new AgentRunner which routes through the engine's scheduler,
        ensuring proper GPU management and output validation.

        Key change from previous version:
        - Empty outputs score 0.0 (not default 0.5)
        - Uses engine infrastructure instead of direct client
        - Supports optillm technique routing via model name prefix
        """
        import time
        from ..agents.evolution.runner import get_runner
        from ..models.versioning import AgentConfig

        runner = await get_runner()
        scores = []
        total_latency = 0
        total_tokens = 0

        # Determine effective model name with technique prefix
        effective_model = config.model
        if config.technique:
            effective_model = f"{config.technique}-{config.model}"

        # Create AgentConfig from CandidateConfig
        agent_config = AgentConfig(
            system_prompt=config.system_prompt,
            temperature=config.temperature,
            model=effective_model,
            max_tokens=1024,
            optillm_technique=config.technique,
            technique_params=config.technique_params,
        )

        for example in examples:
            start = time.perf_counter()

            # Generate output with candidate config via engine
            result = await runner.invoke(agent_config, example.input_prompt)

            latency = (time.perf_counter() - start) * 1000
            total_latency += latency

            # Estimate token usage (rough approximation)
            if result.success and result.content:
                total_tokens += len(result.content.split()) * 1.3  # ~1.3 tokens per word

            # CRITICAL: Empty output = score 0.0 (not 0.5)
            if not result.success or not result.content.strip():
                scores.append(0.0)
                continue

            output = result.content

            # Score the output
            score = await self._score_output(output, example)
            scores.append(score)

        # Store metrics for Pareto optimization
        config.latency_ms = int(total_latency)
        config.tokens_used = int(total_tokens)
        if total_tokens > 0 and scores:
            avg_score = sum(scores) / len(scores)
            config.token_efficiency = avg_score / (total_tokens / 1000)  # quality per ktok

        return scores

    async def _score_output(
        self,
        output: str,
        example: TaskExample,
    ) -> float:
        """Score an output against an example.

        Uses heuristic scoring to avoid circular LLM evaluation.
        For more robust scoring, use the tiered evaluator separately.

        Args:
            output: Generated output
            example: Task example

        Returns:
            Score 0.0-1.0
        """
        # Empty check (should not reach here due to validation above)
        if not output or not output.strip():
            return 0.0

        output_lower = output.lower()

        # If we have expected output, compare
        if example.expected_output:
            expected_lower = example.expected_output.lower()

            # Simple overlap scoring
            output_words = set(output_lower.split())
            expected_words = set(expected_lower.split())

            if not expected_words:
                return 0.5  # No expected words to compare

            overlap = len(output_words & expected_words)
            coverage = overlap / len(expected_words)

            # Combine coverage with length factor
            length_ratio = min(len(output.split()) / max(len(example.expected_output.split()), 1), 2.0) / 2.0

            return min((coverage + length_ratio) / 2, 1.0)

        # Self-evaluation without reference
        # Check for substantive response
        word_count = len(output.split())
        has_structure = any(marker in output for marker in [
            "1.", "2.", "•", "-", "First", "Second", ":", "\n\n"
        ])

        # Length score (prefer 50-300 words)
        if word_count < 20:
            length_score = 0.2
        elif word_count < 50:
            length_score = 0.4
        elif word_count < 300:
            length_score = 0.8
        else:
            length_score = 0.6  # Slightly penalize very long

        # Structure score
        structure_score = 0.7 if has_structure else 0.3

        # Relevance check - look for prompt keywords in output
        prompt_words = set(example.input_prompt.lower().split())
        output_words = set(output_lower.split())
        relevance = len(prompt_words & output_words) / max(len(prompt_words), 1)
        relevance_score = min(relevance * 2, 1.0)

        return (length_score + structure_score + relevance_score) / 3

    async def _evaluate_config_parallel(
        self,
        config: CandidateConfig,
        examples: list[TaskExample],
    ) -> list[float]:
        """Evaluate a config in parallel across multiple endpoints.

        Uses the parallel inference client to distribute evaluations
        across all available GPU endpoints for ~6x speedup.

        Updated to match sequential evaluation:
        - Empty outputs score 0.0 (not 0.5)
        - Uses heuristic scoring instead of LLM self-evaluation
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

        # Phase 2: Score outputs using heuristics (no LLM self-eval)
        scores = []
        for example, gen_result in zip(examples, generate_results):
            # CRITICAL: Failed generation = score 0.0 (not 0.5)
            if not gen_result.success:
                scores.append(0.0)
                continue

            output = gen_result.content

            # CRITICAL: Empty output = score 0.0 (not 0.5)
            if not output or not output.strip():
                scores.append(0.0)
                continue

            # Use same heuristic scoring as sequential
            score = await self._score_output(output, example)
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

        from gaius.client import get_grpc_client
        client = await get_grpc_client()

        scores = []
        for example in examples[:3]:  # Limit frontier calls
            # Generate output
            result = await client.call(
                service="Scheduler",
                action="complete",
                params={
                    "prompt": example.input_prompt,
                    "system_prompt": config.system_prompt,
                    "agent": "fast",
                    "temperature": config.temperature,
                    "max_tokens": 1024,
                },
            )

            # Evaluate with frontier
            eval_result = await evaluator.evaluate(
                agent_output=result.get("content", ""),
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
