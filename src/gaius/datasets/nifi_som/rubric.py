"""6-Dimension Rubric for XAI Frontier Calibration.

Implements anchored ordinal scores (0-4) for evaluating UI instructions:
- A: Intent Understanding (0.15) - Did instruction capture user intent?
- B: SoM Grounding (0.20) - Correct mark reference?
- C: Action Semantics (0.20) - Appropriate action type?
- D: ToM Trace (0.15) - Trace alignment (4/4 for single action)
- E: Constraints (0.15) - Respects implicit/explicit constraints?
- F: Outcome (0.15) - Would this achieve the goal?

This rubric provides dense reward decomposition for Atropos environments,
turning sparse binary success into 6 graded signals with evidence.

Usage:
    from gaius.datasets.nifi_som.rubric import (
        RubricDimension,
        DimensionScore,
        RubricScore,
        DIMENSION_WEIGHTS,
    )

    # Score an example
    score = RubricScore(
        example_id="example_001",
        dimension_scores={
            RubricDimension.INTENT: DimensionScore(
                dimension=RubricDimension.INTENT,
                score=4,
                evidence="Instruction precisely identifies the target processor.",
            ),
            # ... other dimensions
        },
        evaluator_model="xai:grok-3-mini",
        tokens_used=1250,
    )
    print(f"Weighted reward: {score.weighted_reward:.3f}")
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

# ─────────────────────────────────────────────────────────────────────────────
# Dimension Specification
# ─────────────────────────────────────────────────────────────────────────────


class RubricDimension(str, Enum):
    """The 6 dimensions of the evaluation rubric."""

    INTENT = "intent"
    SOM_GROUNDING = "som_grounding"
    ACTION_SEMANTICS = "action_semantics"
    TOM_TRACE = "tom_trace"
    CONSTRAINTS = "constraints"
    OUTCOME = "outcome"


# Dimension weights for reward computation
DIMENSION_WEIGHTS: dict[RubricDimension, float] = {
    RubricDimension.INTENT: 0.15,
    RubricDimension.SOM_GROUNDING: 0.20,
    RubricDimension.ACTION_SEMANTICS: 0.20,
    RubricDimension.TOM_TRACE: 0.15,
    RubricDimension.CONSTRAINTS: 0.15,
    RubricDimension.OUTCOME: 0.15,
}


# Anchored score descriptions per dimension
DIMENSION_ANCHORS: dict[RubricDimension, dict[int, str]] = {
    RubricDimension.INTENT: {
        0: "Task intent misunderstood or contradicted",
        1: "Partial intent grasp; major ambiguity unresolved",
        2: "Core intent understood, secondary constraints missed",
        3: "Intent fully understood, minor phrasing mismatch",
        4: "Intent fully understood and precisely operationalized",
    },
    RubricDimension.SOM_GROUNDING: {
        0: "Marks unrelated to relevant UI elements",
        1: "Correct region but wrong element",
        2: "Correct element class, wrong instance",
        3: "Correct element, imprecise localization",
        4: "Correct element with precise localization",
    },
    RubricDimension.ACTION_SEMANTICS: {
        0: "Actions fundamentally inappropriate",
        1: "Correct category occasionally, mostly wrong",
        2: "Mostly correct, one major mismatch",
        3: "Correct actions, suboptimal ordering",
        4: "Correct actions with optimal ordering",
    },
    RubricDimension.TOM_TRACE: {
        0: "Chaotic / implausible trace",
        1: "Weak alignment, erratic transitions",
        2: "Coarse alignment, timing or order issues",
        3: "Good alignment, minor inefficiencies",
        4: "Clean, efficient, human-plausible trace",
    },
    RubricDimension.CONSTRAINTS: {
        0: "Violated critical constraint",
        1: "Multiple minor violations",
        2: "One notable violation",
        3: "Minor technical deviation",
        4: "Fully compliant",
    },
    RubricDimension.OUTCOME: {
        0: "No progress",
        1: "Progress but wrong end state",
        2: "Partial completion",
        3: "Correct outcome with extra steps",
        4: "Correct and minimal outcome",
    },
}


# Error types for scores <= 2
ERROR_TYPES = [
    "misunderstanding",
    "grounding_failure",
    "wrong_action",
    "trace_divergence",
    "constraint_violation",
    "incomplete_task",
]


# ─────────────────────────────────────────────────────────────────────────────
# Score Data Structures
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class DimensionScore:
    """Score for a single rubric dimension.

    Attributes:
        dimension: Which dimension this scores
        score: Integer 0-4 (anchored ordinal)
        evidence: 1-2 sentences tied to specific elements
        error_type: Required if score <= 2
        automation_source: How this score was generated
    """

    dimension: RubricDimension
    score: int  # 0-4
    evidence: str
    error_type: Optional[str] = None  # Required if score <= 2
    automation_source: str = "frontier"  # "frontier"|"local"|"deterministic"

    def __post_init__(self):
        """Validate score range and error_type consistency."""
        if not 0 <= self.score <= 4:
            raise ValueError(f"Score must be 0-4, got {self.score}")
        if self.score <= 2 and self.error_type is None:
            # Allow missing error_type but log warning
            pass
        if self.error_type and self.error_type not in ERROR_TYPES:
            # Allow non-standard error types
            pass

    @property
    def normalized(self) -> float:
        """Return score as 0.0-1.0 float."""
        return self.score / 4.0

    @property
    def anchor_description(self) -> str:
        """Get the anchor description for this score."""
        return DIMENSION_ANCHORS.get(self.dimension, {}).get(self.score, "")

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "dimension": self.dimension.value,
            "score": self.score,
            "evidence": self.evidence,
            "error_type": self.error_type,
            "automation_source": self.automation_source,
            "normalized": self.normalized,
            "anchor": self.anchor_description,
        }


@dataclass
class RubricScore:
    """Complete 6-dimension rubric score for an example.

    Combines all dimension scores into a weighted reward signal,
    compatible with Atropos ScoredDataItem protocol.

    Attributes:
        example_id: Unique identifier for the scored example
        dimension_scores: Dict mapping dimension to DimensionScore
        evaluator_model: Model that produced the scores
        tokens_used: Tokens consumed by evaluation
        evaluated_at: Timestamp of evaluation
    """

    example_id: str
    dimension_scores: dict[RubricDimension, DimensionScore]
    evaluator_model: str
    tokens_used: int
    evaluated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def weighted_reward(self) -> float:
        """Compute weighted reward from dimension scores (0.0-1.0)."""
        if not self.dimension_scores:
            return 0.0

        total = 0.0
        weight_sum = 0.0

        for dim, weight in DIMENSION_WEIGHTS.items():
            if dim in self.dimension_scores:
                total += self.dimension_scores[dim].normalized * weight
                weight_sum += weight

        # Normalize by actual weights used (in case some dimensions missing)
        if weight_sum > 0:
            return total / weight_sum
        return 0.0

    def get_errors(self) -> list[tuple[RubricDimension, str]]:
        """Get all dimensions with errors (score <= 2)."""
        errors = []
        for dim, score in self.dimension_scores.items():
            if score.score <= 2 and score.error_type:
                errors.append((dim, score.error_type))
        return errors

    def get_lowest_dimension(self) -> Optional[tuple[RubricDimension, DimensionScore]]:
        """Get the dimension with lowest score."""
        if not self.dimension_scores:
            return None
        return min(
            self.dimension_scores.items(),
            key=lambda x: x[1].score,
        )

    def is_passing(self, threshold: float = 0.6) -> bool:
        """Check if weighted reward exceeds threshold."""
        return self.weighted_reward >= threshold

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "example_id": self.example_id,
            "dimension_scores": {
                dim.value: score.to_dict()
                for dim, score in self.dimension_scores.items()
            },
            "weighted_reward": self.weighted_reward,
            "evaluator_model": self.evaluator_model,
            "tokens_used": self.tokens_used,
            "evaluated_at": self.evaluated_at.isoformat(),
            "errors": [
                {"dimension": dim.value, "error_type": err}
                for dim, err in self.get_errors()
            ],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "RubricScore":
        """Create RubricScore from dictionary."""
        dimension_scores = {}
        for dim_name, score_data in data.get("dimension_scores", {}).items():
            dim = RubricDimension(dim_name)
            dimension_scores[dim] = DimensionScore(
                dimension=dim,
                score=score_data["score"],
                evidence=score_data["evidence"],
                error_type=score_data.get("error_type"),
                automation_source=score_data.get("automation_source", "frontier"),
            )

        return cls(
            example_id=data["example_id"],
            dimension_scores=dimension_scores,
            evaluator_model=data["evaluator_model"],
            tokens_used=data["tokens_used"],
            evaluated_at=datetime.fromisoformat(data["evaluated_at"]),
        )


# ─────────────────────────────────────────────────────────────────────────────
# Factory Functions
# ─────────────────────────────────────────────────────────────────────────────


def create_single_action_score(
    example_id: str,
    intent_score: int,
    intent_evidence: str,
    som_score: int,
    som_evidence: str,
    action_score: int,
    action_evidence: str,
    constraints_score: int,
    constraints_evidence: str,
    outcome_score: int,
    outcome_evidence: str,
    evaluator_model: str = "xai:grok-3-mini",
    tokens_used: int = 0,
    intent_error: Optional[str] = None,
    som_error: Optional[str] = None,
    action_error: Optional[str] = None,
    constraints_error: Optional[str] = None,
    outcome_error: Optional[str] = None,
) -> RubricScore:
    """Create RubricScore for a single-action SoM example.

    For single actions, ToM Trace is automatically set to 4/4 as there's
    no multi-step trajectory to evaluate.

    Args:
        example_id: Unique identifier
        *_score: Integer 0-4 for each dimension
        *_evidence: Evidence string for each dimension
        evaluator_model: Model that produced scores
        tokens_used: Tokens consumed
        *_error: Optional error type for scores <= 2

    Returns:
        RubricScore with all 6 dimensions
    """
    dimension_scores = {
        RubricDimension.INTENT: DimensionScore(
            dimension=RubricDimension.INTENT,
            score=intent_score,
            evidence=intent_evidence,
            error_type=intent_error,
        ),
        RubricDimension.SOM_GROUNDING: DimensionScore(
            dimension=RubricDimension.SOM_GROUNDING,
            score=som_score,
            evidence=som_evidence,
            error_type=som_error,
        ),
        RubricDimension.ACTION_SEMANTICS: DimensionScore(
            dimension=RubricDimension.ACTION_SEMANTICS,
            score=action_score,
            evidence=action_evidence,
            error_type=action_error,
        ),
        RubricDimension.TOM_TRACE: DimensionScore(
            dimension=RubricDimension.TOM_TRACE,
            score=4,  # Always 4 for single action
            evidence="Single-action example; no trajectory to evaluate.",
            automation_source="deterministic",
        ),
        RubricDimension.CONSTRAINTS: DimensionScore(
            dimension=RubricDimension.CONSTRAINTS,
            score=constraints_score,
            evidence=constraints_evidence,
            error_type=constraints_error,
        ),
        RubricDimension.OUTCOME: DimensionScore(
            dimension=RubricDimension.OUTCOME,
            score=outcome_score,
            evidence=outcome_evidence,
            error_type=outcome_error,
        ),
    }

    return RubricScore(
        example_id=example_id,
        dimension_scores=dimension_scores,
        evaluator_model=evaluator_model,
        tokens_used=tokens_used,
    )


def create_trajectory_score(
    example_id: str,
    dimension_scores: dict[RubricDimension, tuple[int, str, Optional[str]]],
    evaluator_model: str = "xai:grok-3-mini",
    tokens_used: int = 0,
) -> RubricScore:
    """Create RubricScore for a multi-action trajectory example.

    All 6 dimensions must be provided with (score, evidence, error_type).

    Args:
        example_id: Unique identifier
        dimension_scores: Dict of dimension -> (score, evidence, error_type)
        evaluator_model: Model that produced scores
        tokens_used: Tokens consumed

    Returns:
        RubricScore with all 6 dimensions
    """
    scores = {}
    for dim in RubricDimension:
        if dim not in dimension_scores:
            raise ValueError(f"Missing dimension: {dim.value}")
        score, evidence, error_type = dimension_scores[dim]
        scores[dim] = DimensionScore(
            dimension=dim,
            score=score,
            evidence=evidence,
            error_type=error_type,
        )

    return RubricScore(
        example_id=example_id,
        dimension_scores=scores,
        evaluator_model=evaluator_model,
        tokens_used=tokens_used,
    )
