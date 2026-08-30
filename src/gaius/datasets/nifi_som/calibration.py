"""XAI Calibration Orchestrator for NiFi SoM/ToM Dataset Pipeline.

Implements strategic, budget-aware sampling to maximize signal from
limited frontier model calls (50/day, 200/week). Uses uncertainty-weighted
stratified sampling to select examples for XAI evaluation.

Key Components:
- CalibrationOrchestrator: Main entry point for inline and batch calibration
- UncertaintySampler: Select examples using uncertainty + stratification
- CalibrationRegistry: Track per-dimension calibration factors with EMA updates

Usage:
    from gaius.datasets.nifi_som.calibration import (
        CalibrationOrchestrator,
        CalibrationConfig,
    )
    from gaius.models.tiered_evaluation import EvalBudget

    budget = EvalBudget(daily_limit=50, weekly_limit=200)
    orchestrator = CalibrationOrchestrator(budget=budget)

    # Inline calibration during generation (5% sample)
    result = await orchestrator.maybe_calibrate_inline(
        candidate=candidate,
        marks=marks,
        context=context,
    )

    # Batch calibration post-processing
    results = await orchestrator.calibrate_batch(examples)
"""

import asyncio
import json
import logging
import random
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from .rubric import (
    RubricDimension,
    RubricScore,
    DimensionScore,
    DIMENSION_WEIGHTS,
)
from .prompts.rubric import (
    build_rubric_prompt,
    parse_rubric_response,
    compute_weighted_reward,
)

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class CalibrationConfig:
    """Configuration for XAI calibration."""

    # Inline sampling during generation
    inline_sample_rate: float = 0.05  # 5% of examples
    inline_budget: int = 5  # Max per day for inline

    # Batch sampling post-processing
    batch_sample_budget: int = 30  # Per day

    # Uncertainty band for triggering calibration
    uncertainty_band: tuple[float, float] = (0.4, 0.7)

    # EMA smoothing for calibration factor updates
    ema_alpha: float = 0.1

    # Cold start settings
    cold_start_budget_multiplier: float = 0.8  # Use 80% of budget during cold start
    cold_start_global_threshold: int = 30  # Exit cold start after N global samples
    cold_start_per_type_threshold: int = 10  # Exit cold start after N per-type samples

    # Stratification weights
    strata_weights: dict[str, float] = field(default_factory=lambda: {
        "low": 0.20,   # Score < 0.4
        "mid": 0.50,   # Score 0.4-0.7
        "high": 0.30,  # Score >= 0.7
    })


@dataclass
class LocalScoreInput:
    """Local scores provided as input to calibration."""

    example_id: str
    instruction: str
    target_name: str
    target_type: str
    marks: list[dict]
    action_type: str

    # Local 4-dimension scores (from quality.py)
    clarity: float
    naturalness: float
    specificity: float
    conciseness: float
    overall: float

    # Optional context
    constraints: Optional[list[str]] = None
    trajectory: Optional[list[dict]] = None
    screenshot_context: str = ""


# ─────────────────────────────────────────────────────────────────────────────
# Calibration Registry
# ─────────────────────────────────────────────────────────────────────────────


class CalibrationRegistry:
    """Track calibration factors per dimension and target type.

    Maintains global and per-type calibration factors with EMA updates
    for stability. Used to adjust local scores to align with XAI assessments.
    """

    def __init__(self, ema_alpha: float = 0.1):
        """Initialize registry.

        Args:
            ema_alpha: EMA smoothing factor (0.1 = slow adaptation)
        """
        self.ema_alpha = ema_alpha

        # Global calibration factors per dimension
        self._global_factors: dict[RubricDimension, float] = {
            dim: 1.0 for dim in RubricDimension
        }

        # Per-type calibration factors
        self._type_factors: dict[str, dict[RubricDimension, float]] = {}

        # Sample counts for cold start detection
        self._global_count = 0
        self._type_counts: dict[str, int] = {}

        # History for analysis
        self._history: list[dict] = []

    def is_cold_start(
        self,
        global_threshold: int = 30,
        per_type_threshold: int = 10,
    ) -> bool:
        """Check if still in cold start phase."""
        if self._global_count < global_threshold:
            return True
        # Also check if any type is under threshold
        for count in self._type_counts.values():
            if count < per_type_threshold:
                return True
        return False

    def update(
        self,
        target_type: str,
        local_scores: dict[str, float],
        xai_scores: dict[RubricDimension, int],
    ) -> None:
        """Update calibration factors based on local vs XAI comparison.

        Args:
            target_type: Type of UI element (processor, connection, etc.)
            local_scores: Local model's dimension scores (0-1)
            xai_scores: XAI's dimension scores (0-4)
        """
        # Map local 4-dim to 6-dim rubric (approximate)
        local_mapped = self._map_local_to_rubric(local_scores)

        # Update global factors
        for dim in RubricDimension:
            if dim in xai_scores:
                xai_normalized = xai_scores[dim] / 4.0
                local_val = local_mapped.get(dim, 0.5)

                if local_val > 0:
                    # Compute correction ratio
                    correction = xai_normalized / local_val
                    correction = max(0.5, min(1.5, correction))  # Clamp

                    # EMA update
                    old_factor = self._global_factors[dim]
                    new_factor = old_factor * (1 - self.ema_alpha) + correction * self.ema_alpha
                    self._global_factors[dim] = new_factor

        # Update per-type factors
        if target_type not in self._type_factors:
            self._type_factors[target_type] = {dim: 1.0 for dim in RubricDimension}
            self._type_counts[target_type] = 0

        for dim in RubricDimension:
            if dim in xai_scores:
                xai_normalized = xai_scores[dim] / 4.0
                local_val = local_mapped.get(dim, 0.5)

                if local_val > 0:
                    correction = xai_normalized / local_val
                    correction = max(0.5, min(1.5, correction))

                    old_factor = self._type_factors[target_type][dim]
                    new_factor = old_factor * (1 - self.ema_alpha) + correction * self.ema_alpha
                    self._type_factors[target_type][dim] = new_factor

        # Update counts
        self._global_count += 1
        self._type_counts[target_type] = self._type_counts.get(target_type, 0) + 1

        # Record history
        self._history.append({
            "target_type": target_type,
            "local_scores": local_scores,
            "xai_scores": {d.value: s for d, s in xai_scores.items()},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    def get_factor(
        self,
        dimension: RubricDimension,
        target_type: Optional[str] = None,
    ) -> float:
        """Get calibration factor for a dimension.

        Args:
            dimension: Which dimension
            target_type: Optional target type for per-type factor

        Returns:
            Calibration factor (multiply local score by this)
        """
        if target_type and target_type in self._type_factors:
            return self._type_factors[target_type].get(
                dimension,
                self._global_factors[dimension],
            )
        return self._global_factors[dimension]

    def calibrate_score(
        self,
        dimension: RubricDimension,
        local_score: float,
        target_type: Optional[str] = None,
    ) -> float:
        """Apply calibration factor to a local score.

        Args:
            dimension: Which dimension
            local_score: Raw local score (0-1)
            target_type: Optional target type

        Returns:
            Calibrated score clamped to [0.0, 1.0]
        """
        factor = self.get_factor(dimension, target_type)
        calibrated = local_score * factor
        return max(0.0, min(1.0, calibrated))

    def _map_local_to_rubric(
        self,
        local_scores: dict[str, float],
    ) -> dict[RubricDimension, float]:
        """Map 4-dimension local scores to 6-dimension rubric.

        Approximate mapping:
        - clarity → intent, som_grounding
        - naturalness → action_semantics
        - specificity → som_grounding, constraints
        - conciseness → outcome
        """
        clarity = local_scores.get("clarity", 0.5)
        naturalness = local_scores.get("naturalness", 0.5)
        specificity = local_scores.get("specificity", 0.5)
        conciseness = local_scores.get("conciseness", 0.5)

        return {
            RubricDimension.INTENT: clarity,
            RubricDimension.SOM_GROUNDING: (clarity + specificity) / 2,
            RubricDimension.ACTION_SEMANTICS: naturalness,
            RubricDimension.TOM_TRACE: 1.0,  # Assume perfect for single actions
            RubricDimension.CONSTRAINTS: specificity,
            RubricDimension.OUTCOME: (specificity + conciseness) / 2,
        }

    def to_dict(self) -> dict:
        """Export registry state for persistence."""
        return {
            "global_factors": {d.value: f for d, f in self._global_factors.items()},
            "type_factors": {
                t: {d.value: f for d, f in factors.items()}
                for t, factors in self._type_factors.items()
            },
            "global_count": self._global_count,
            "type_counts": self._type_counts,
            "ema_alpha": self.ema_alpha,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "CalibrationRegistry":
        """Restore registry from persisted state."""
        registry = cls(ema_alpha=data.get("ema_alpha", 0.1))

        for dim_name, factor in data.get("global_factors", {}).items():
            dim = RubricDimension(dim_name)
            registry._global_factors[dim] = factor

        for type_name, factors in data.get("type_factors", {}).items():
            registry._type_factors[type_name] = {}
            for dim_name, factor in factors.items():
                dim = RubricDimension(dim_name)
                registry._type_factors[type_name][dim] = factor

        registry._global_count = data.get("global_count", 0)
        registry._type_counts = data.get("type_counts", {})

        return registry


# ─────────────────────────────────────────────────────────────────────────────
# Uncertainty Sampler
# ─────────────────────────────────────────────────────────────────────────────


class UncertaintySampler:
    """Select examples for XAI using uncertainty-weighted stratified sampling.

    Prioritizes examples where:
    1. Local score is in uncertain band (0.4-0.7)
    2. Dimension scores have high variance
    3. Under-sampled target types

    Uses stratified sampling to ensure coverage across score ranges.
    """

    def __init__(self, config: CalibrationConfig):
        """Initialize sampler.

        Args:
            config: Calibration configuration
        """
        self.config = config

    def compute_uncertainty(self, local_input: LocalScoreInput) -> float:
        """Compute uncertainty score for an example.

        Higher uncertainty = more valuable for calibration.

        Args:
            local_input: Local scores for the example

        Returns:
            Uncertainty score in [0, 1]
        """
        # Score-based uncertainty: highest at 0.5, lowest at 0 and 1
        score_uncertainty = 1.0 - abs(local_input.overall - 0.5) * 2

        # Dimension variance: high variance = uncertain
        dims = [
            local_input.clarity,
            local_input.naturalness,
            local_input.specificity,
            local_input.conciseness,
        ]
        dim_range = max(dims) - min(dims)

        # Combined uncertainty
        uncertainty = 0.6 * score_uncertainty + 0.4 * dim_range

        return max(0.0, min(1.0, uncertainty))

    def is_in_uncertainty_band(self, local_input: LocalScoreInput) -> bool:
        """Check if example falls in uncertainty band."""
        low, high = self.config.uncertainty_band
        return low <= local_input.overall <= high

    def select_samples(
        self,
        examples: list[LocalScoreInput],
        budget: int,
        type_counts: Optional[dict[str, int]] = None,
    ) -> list[LocalScoreInput]:
        """Select examples for XAI calibration.

        Uses stratified sampling by score range, with uncertainty weighting
        within each stratum.

        Args:
            examples: All available examples
            budget: Maximum samples to select
            type_counts: Current per-type sample counts (for balancing)

        Returns:
            Selected examples for calibration
        """
        if not examples or budget <= 0:
            return []

        # Stratify by score range
        low = [e for e in examples if e.overall < 0.4]
        mid = [e for e in examples if 0.4 <= e.overall < 0.7]
        high = [e for e in examples if e.overall >= 0.7]

        # Compute per-stratum budgets
        weights = self.config.strata_weights
        low_budget = int(budget * weights["low"])
        mid_budget = int(budget * weights["mid"])
        high_budget = budget - low_budget - mid_budget

        selected = []

        # Sample from each stratum, prioritizing by uncertainty
        for stratum, stratum_budget in [(low, low_budget), (mid, mid_budget), (high, high_budget)]:
            if not stratum or stratum_budget <= 0:
                continue

            # Sort by uncertainty (descending)
            sorted_stratum = sorted(
                stratum,
                key=lambda x: self.compute_uncertainty(x),
                reverse=True,
            )

            # Apply type balancing if we have counts
            if type_counts:
                sorted_stratum = self._balance_by_type(sorted_stratum, type_counts)

            # Take top N by uncertainty
            selected.extend(sorted_stratum[:stratum_budget])

        return selected

    def _balance_by_type(
        self,
        examples: list[LocalScoreInput],
        type_counts: dict[str, int],
    ) -> list[LocalScoreInput]:
        """Reorder examples to prioritize under-sampled types."""
        if not type_counts:
            return examples

        # Compute type priorities (lower count = higher priority)
        min_count = min(type_counts.values()) if type_counts else 0
        max_count = max(type_counts.values()) if type_counts else 1

        def priority_key(example: LocalScoreInput) -> tuple[float, float]:
            type_count = type_counts.get(example.target_type, 0)
            # Invert so lower count gets higher priority
            type_priority = 1.0 - (type_count - min_count) / max(1, max_count - min_count)
            uncertainty = self.compute_uncertainty(example)
            return (type_priority, uncertainty)

        return sorted(examples, key=priority_key, reverse=True)


# ─────────────────────────────────────────────────────────────────────────────
# Calibration Orchestrator
# ─────────────────────────────────────────────────────────────────────────────


class CalibrationOrchestrator:
    """Main orchestrator for XAI calibration.

    Manages budget-aware inline and batch calibration using the 6-dimension
    rubric. Integrates with EvalBudget from tiered_evaluation.py.

    Usage:
        orchestrator = CalibrationOrchestrator(budget=budget)

        # Inline: during generation (5% sample or high uncertainty)
        result = await orchestrator.maybe_calibrate_inline(candidate, marks, context)

        # Batch: post-processing strategic sampling
        results = await orchestrator.calibrate_batch(examples)
    """

    def __init__(
        self,
        budget: "EvalBudget",
        config: Optional[CalibrationConfig] = None,
        registry: Optional[CalibrationRegistry] = None,
    ):
        """Initialize orchestrator.

        Args:
            budget: EvalBudget from tiered_evaluation
            config: Optional CalibrationConfig (uses defaults if None)
            registry: Optional CalibrationRegistry (creates new if None)
        """
        self.budget = budget
        self.config = config or CalibrationConfig()
        self.registry = registry or CalibrationRegistry(ema_alpha=self.config.ema_alpha)
        self.sampler = UncertaintySampler(self.config)

        self._inline_count_today = 0
        self._client = None

    async def _get_client(self):
        """Lazy-load XAI client."""
        if self._client is None:
            try:
                from gaius.client.engine_client import EngineInferenceClient as InferenceClient
                self._client = InferenceClient()
            except ImportError:
                logger.warning("InferenceClient not available")
        return self._client

    def _can_calibrate(self, is_inline: bool = False) -> bool:
        """Check if budget allows calibration."""
        if not self.budget.can_use_xai():
            return False

        if is_inline:
            return self._inline_count_today < self.config.inline_budget

        return True

    async def maybe_calibrate_inline(
        self,
        local_input: LocalScoreInput,
    ) -> Optional[RubricScore]:
        """Maybe calibrate a single example during generation.

        Called during instruction generation. Calibrates if:
        - Random sample (5% rate)
        - OR example is in uncertainty band
        - AND budget allows

        Args:
            local_input: Local scores and context

        Returns:
            RubricScore if calibrated, None otherwise
        """
        if not self._can_calibrate(is_inline=True):
            return None

        # Check if should sample
        should_sample = (
            random.random() < self.config.inline_sample_rate
            or self.sampler.is_in_uncertainty_band(local_input)
        )

        if not should_sample:
            return None

        # Perform calibration
        result = await self._evaluate_with_xai(local_input)

        if result:
            self._inline_count_today += 1
            # Update registry
            xai_scores = {
                dim: result.dimension_scores[dim].score
                for dim in result.dimension_scores
            }
            self.registry.update(
                target_type=local_input.target_type,
                local_scores={
                    "clarity": local_input.clarity,
                    "naturalness": local_input.naturalness,
                    "specificity": local_input.specificity,
                    "conciseness": local_input.conciseness,
                },
                xai_scores=xai_scores,
            )

        return result

    async def calibrate_batch(
        self,
        examples: list[LocalScoreInput],
    ) -> list[RubricScore]:
        """Calibrate a batch of examples using strategic sampling.

        Post-processing calibration using stratified sampling by score
        range and uncertainty weighting.

        Args:
            examples: All examples to potentially calibrate

        Returns:
            List of RubricScore for calibrated examples
        """
        if not examples:
            return []

        # Determine budget based on cold start status
        if self.registry.is_cold_start(
            self.config.cold_start_global_threshold,
            self.config.cold_start_per_type_threshold,
        ):
            budget = int(
                self.config.batch_sample_budget
                * self.config.cold_start_budget_multiplier
            )
            logger.info(f"Cold start: using {budget} samples (80% of batch budget)")
        else:
            budget = self.config.batch_sample_budget

        # Cap by remaining XAI budget
        budget = min(budget, self.budget.remaining_daily)

        if budget <= 0:
            logger.warning("No XAI budget remaining for batch calibration")
            return []

        # Select samples
        type_counts = self.registry._type_counts if not self.registry.is_cold_start() else None
        selected = self.sampler.select_samples(examples, budget, type_counts)

        logger.info(f"Selected {len(selected)} examples for XAI calibration")

        # Evaluate selected examples
        results = []
        for local_input in selected:
            if not self.budget.can_use_xai():
                logger.warning("XAI budget exhausted during batch calibration")
                break

            result = await self._evaluate_with_xai(local_input)
            if result:
                results.append(result)

                # Update registry
                xai_scores = {
                    dim: result.dimension_scores[dim].score
                    for dim in result.dimension_scores
                }
                self.registry.update(
                    target_type=local_input.target_type,
                    local_scores={
                        "clarity": local_input.clarity,
                        "naturalness": local_input.naturalness,
                        "specificity": local_input.specificity,
                        "conciseness": local_input.conciseness,
                    },
                    xai_scores=xai_scores,
                )

        logger.info(f"Completed {len(results)} XAI calibrations")
        return results

    async def _evaluate_with_xai(
        self,
        local_input: LocalScoreInput,
    ) -> Optional[RubricScore]:
        """Evaluate a single example with XAI.

        Args:
            local_input: Example to evaluate

        Returns:
            RubricScore or None on failure
        """
        client = await self._get_client()
        if client is None:
            return None

        # Build prompt
        system_prompt, user_prompt = build_rubric_prompt(
            instruction=local_input.instruction,
            target_name=local_input.target_name,
            target_type=local_input.target_type,
            action_type=local_input.action_type,
            marks=local_input.marks,
            screenshot_context=local_input.screenshot_context,
            constraints=local_input.constraints,
            trajectory=local_input.trajectory,
        )

        try:
            from gaius.client.engine_client import Message

            messages = [
                Message(role="system", content=system_prompt),
                Message(role="user", content=user_prompt),
            ]

            # XAI judge via the engine's external backend lane (Engine-First)
            result = await client.complete(
                messages,
                model="xai",
                temperature=0.3,  # Low temp for consistent eval
            )

            # Record budget use
            tokens = result.input_tokens + result.output_tokens
            self.budget.record_use(tokens)

            # Parse response
            parsed = parse_rubric_response(result.content)

            # Convert to RubricScore
            dimension_scores = {}
            for dim_name, score_data in parsed.items():
                dim = RubricDimension(dim_name)
                dimension_scores[dim] = DimensionScore(
                    dimension=dim,
                    score=score_data["score"],
                    evidence=score_data["evidence"],
                    error_type=score_data.get("error_type"),
                    automation_source="frontier",
                )

            return RubricScore(
                example_id=local_input.example_id,
                dimension_scores=dimension_scores,
                evaluator_model="xai:grok-3-mini",
                tokens_used=tokens,
            )

        except Exception as e:
            logger.error(f"XAI evaluation failed: {e}")
            return None

    def get_calibrated_score(
        self,
        local_input: LocalScoreInput,
    ) -> dict[RubricDimension, float]:
        """Get calibrated scores without XAI call.

        Applies calibration factors from registry to local scores.

        Args:
            local_input: Local scores

        Returns:
            Dict of calibrated scores per dimension
        """
        # Map local to rubric dimensions
        mapped = self.registry._map_local_to_rubric({
            "clarity": local_input.clarity,
            "naturalness": local_input.naturalness,
            "specificity": local_input.specificity,
            "conciseness": local_input.conciseness,
        })

        # Apply calibration
        calibrated = {}
        for dim, score in mapped.items():
            calibrated[dim] = self.registry.calibrate_score(
                dim, score, local_input.target_type
            )

        return calibrated

    def get_status(self) -> dict:
        """Get orchestrator status."""
        return {
            "budget": {
                "daily_remaining": self.budget.remaining_daily,
                "weekly_remaining": self.budget.remaining_weekly,
            },
            "inline_count_today": self._inline_count_today,
            "registry": {
                "global_count": self.registry._global_count,
                "type_counts": self.registry._type_counts,
                "is_cold_start": self.registry.is_cold_start(),
            },
            "config": {
                "inline_sample_rate": self.config.inline_sample_rate,
                "inline_budget": self.config.inline_budget,
                "batch_sample_budget": self.config.batch_sample_budget,
            },
        }


# ─────────────────────────────────────────────────────────────────────────────
# Module-level Singleton
# ─────────────────────────────────────────────────────────────────────────────

_orchestrator: Optional[CalibrationOrchestrator] = None


def get_calibration_orchestrator(
    budget: Optional["EvalBudget"] = None,
    config: Optional[CalibrationConfig] = None,
) -> CalibrationOrchestrator:
    """Get or create calibration orchestrator singleton.

    Args:
        budget: EvalBudget (required on first call)
        config: Optional CalibrationConfig

    Returns:
        CalibrationOrchestrator instance
    """
    global _orchestrator

    if _orchestrator is None:
        if budget is None:
            # Create default budget
            from ...models.tiered_evaluation import EvalBudget
            budget = EvalBudget()
        _orchestrator = CalibrationOrchestrator(budget=budget, config=config)

    return _orchestrator


# Type hint import for runtime
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from ...models.tiered_evaluation import EvalBudget
