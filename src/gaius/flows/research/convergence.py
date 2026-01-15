"""Convergence detection for multi-pass research.

Uses drift-based stopping criteria inspired by ThetaDynamics:
- L2 drift between pass centroids
- Q-value improvement tracking
- Hard pass budget limit

Guru Meditation Codes:
- #RF.00000006.CONVERGEFAIL: Convergence check failed
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class PassResult:
    """Result from a single research pass.

    Supports Metaflow artifact serialization via __getstate__/__setstate__
    to properly handle numpy arrays (centroid).
    """

    pass_number: int
    synthesis: str
    q_value: float
    reward_total: float
    centroid: np.ndarray | None = None  # Embedding centroid for drift detection
    sources_count: int = 0
    duration_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Convert to serializable dict."""
        return {
            "pass_number": self.pass_number,
            "q_value": round(self.q_value, 3),
            "reward_total": round(self.reward_total, 3),
            "sources_count": self.sources_count,
            "duration_ms": self.duration_ms,
            "synthesis_length": len(self.synthesis),
        }

    def __getstate__(self) -> dict[str, Any]:
        """Prepare state for pickling (Metaflow artifact serialization).

        Converts numpy array to list for portable serialization.
        """
        state = self.__dict__.copy()
        if isinstance(self.centroid, np.ndarray):
            state["centroid"] = self.centroid.tolist()
        return state

    def __setstate__(self, state: dict[str, Any]) -> None:
        """Restore state from pickle (Metaflow artifact deserialization).

        Converts list back to numpy array.
        """
        if state.get("centroid") is not None and isinstance(state["centroid"], list):
            state["centroid"] = np.array(state["centroid"])
        self.__dict__.update(state)


def compute_drift(centroid_a: np.ndarray | None, centroid_b: np.ndarray | None) -> float:
    """Compute L2 drift between two embedding centroids.

    Args:
        centroid_a: First centroid embedding.
        centroid_b: Second centroid embedding.

    Returns:
        L2 distance (0 = identical, higher = more drift).
    """
    if centroid_a is None or centroid_b is None:
        return float("inf")

    if centroid_a.shape != centroid_b.shape:
        logger.warning(
            f"Centroid shape mismatch: {centroid_a.shape} vs {centroid_b.shape}"
        )
        return float("inf")

    return float(np.linalg.norm(centroid_a - centroid_b))


def compute_text_drift(text_a: str, text_b: str) -> float:
    """Compute text-based drift as fallback when embeddings unavailable.

    Uses Jaccard distance on word sets as a simple measure.

    Args:
        text_a: First text.
        text_b: Second text.

    Returns:
        Drift score (0 = identical, 1 = completely different).
    """
    import re

    tokens_a = set(
        word.lower()
        for word in re.findall(r"\w+", text_a)
        if len(word) > 3
    )
    tokens_b = set(
        word.lower()
        for word in re.findall(r"\w+", text_b)
        if len(word) > 3
    )

    if not tokens_a or not tokens_b:
        return 1.0

    intersection = len(tokens_a & tokens_b)
    union = len(tokens_a | tokens_b)

    jaccard_similarity = intersection / union if union > 0 else 0
    return 1 - jaccard_similarity


@dataclass
class ConvergenceTracker:
    """Track research convergence across multiple passes.

    Convergence criteria (any triggers stop):
    1. Drift below threshold (information gain plateaued)
    2. Q-value improvement below threshold (quality plateaued)
    3. Max passes reached (budget exhausted)

    Inspired by ThetaDynamics NVAR-based drift detection.

    Supports Metaflow artifact serialization via __getstate__/__setstate__
    to properly handle PassResult objects with numpy arrays.
    """

    # Thresholds
    drift_threshold: float = 0.15  # L2 drift below this = converged
    max_passes: int = 5  # Hard budget limit
    min_q_improvement: float = 0.02  # Q must improve by this much

    # State
    passes: list[PassResult] = field(default_factory=list)

    def __getstate__(self) -> dict[str, Any]:
        """Prepare state for pickling (Metaflow artifact serialization)."""
        state = {
            "drift_threshold": self.drift_threshold,
            "max_passes": self.max_passes,
            "min_q_improvement": self.min_q_improvement,
            "passes": [p.__getstate__() for p in self.passes],
        }
        return state

    def __setstate__(self, state: dict[str, Any]) -> None:
        """Restore state from pickle (Metaflow artifact deserialization)."""
        self.drift_threshold = state.get("drift_threshold", 0.15)
        self.max_passes = state.get("max_passes", 5)
        self.min_q_improvement = state.get("min_q_improvement", 0.02)

        # Restore PassResult objects
        self.passes = []
        for pass_dict in state.get("passes", []):
            pr = PassResult.__new__(PassResult)
            pr.__setstate__(pass_dict)
            self.passes.append(pr)

    def add_pass(self, result: PassResult) -> None:
        """Record a completed pass."""
        self.passes.append(result)
        logger.info(
            f"Pass {result.pass_number} recorded: Q={result.q_value:.3f}, "
            f"reward={result.reward_total:.3f}"
        )

    def should_stop(self) -> tuple[bool, str]:
        """Check if research should stop.

        Returns:
            Tuple of (should_stop, reason).
        """
        if len(self.passes) == 0:
            return False, "no_passes_yet"

        # Check max passes
        if len(self.passes) >= self.max_passes:
            return True, f"max_passes_reached:{self.max_passes}"

        # Need at least 2 passes for comparison
        if len(self.passes) < 2:
            return False, "insufficient_passes"

        current = self.passes[-1]
        previous = self.passes[-2]

        # Check embedding drift (if available)
        if current.centroid is not None and previous.centroid is not None:
            drift = compute_drift(current.centroid, previous.centroid)
            if drift < self.drift_threshold:
                return True, f"drift_converged:{drift:.4f}"
        else:
            # Fall back to text-based drift
            text_drift = compute_text_drift(current.synthesis, previous.synthesis)
            if text_drift < self.drift_threshold:
                return True, f"text_drift_converged:{text_drift:.4f}"

        # Check Q-value improvement
        q_improvement = current.q_value - previous.q_value
        if q_improvement < self.min_q_improvement:
            return True, f"q_plateaued:{q_improvement:.4f}"

        return False, "continuing"

    def get_summary(self) -> dict[str, Any]:
        """Get convergence tracking summary."""
        if not self.passes:
            return {
                "passes": 0,
                "converged": False,
                "reason": "no_passes",
            }

        converged, reason = self.should_stop()

        # Compute statistics
        q_values = [p.q_value for p in self.passes]
        rewards = [p.reward_total for p in self.passes]

        return {
            "passes": len(self.passes),
            "converged": converged,
            "reason": reason,
            "q_values": [round(q, 3) for q in q_values],
            "rewards": [round(r, 3) for r in rewards],
            "q_improvement": round(q_values[-1] - q_values[0], 3) if len(q_values) > 1 else 0,
            "final_q": round(q_values[-1], 3),
            "best_q": round(max(q_values), 3),
            "total_duration_ms": sum(p.duration_ms for p in self.passes),
        }

    def get_best_pass(self) -> PassResult | None:
        """Get the pass with highest Q-value."""
        if not self.passes:
            return None
        return max(self.passes, key=lambda p: p.q_value)


async def compute_centroid(
    texts: list[str],
    use_embedding: bool = True,
) -> np.ndarray | None:
    """Compute centroid embedding for drift detection.

    Args:
        texts: List of texts to embed and average.
        use_embedding: If True, use real embeddings; else return None.

    Returns:
        Centroid embedding vector or None.
    """
    if not use_embedding or not texts:
        return None

    try:
        from gaius.models import get_embeddings

        # Embed all texts using the embeddings service
        embeddings = get_embeddings()
        result = await embeddings.embed_texts(texts)

        # Return mean (centroid) - vectors is (n, 768) ndarray
        return np.mean(result.vectors, axis=0)

    except Exception as e:
        logger.error(f"Failed to compute centroid: {e}")
        from gaius.flows.research import ResearchError
        raise ResearchError(
            f"Centroid computation failed: {e}",
            guru_code="#RF.00000006.CONVERGEFAIL",
            hint="/health fix embeddings",
        ) from e


class AdaptiveConvergenceTracker(ConvergenceTracker):
    """Convergence tracker with adaptive thresholds.

    Adjusts thresholds based on query complexity and prior experience:
    - Complex queries get more passes
    - High-value topics get tighter convergence criteria
    """

    def __init__(
        self,
        query: str,
        prior_q_values: list[float] | None = None,
        **kwargs: Any,
    ):
        super().__init__(**kwargs)
        self.query = query
        self.prior_q_values = prior_q_values or []

        # Adapt thresholds based on query complexity
        self._adapt_thresholds()

    def _adapt_thresholds(self) -> None:
        """Adapt thresholds based on query characteristics."""
        # Longer queries = more complex = more passes
        word_count = len(self.query.split())
        if word_count > 10:
            self.max_passes = min(7, self.max_passes + 2)
            self.drift_threshold *= 0.8  # Tighter convergence

        # If prior research had high Q-values, maintain quality
        if self.prior_q_values and max(self.prior_q_values) > 0.7:
            self.min_q_improvement *= 1.5  # Higher bar for improvement

        logger.debug(
            f"Adapted thresholds: max_passes={self.max_passes}, "
            f"drift={self.drift_threshold:.3f}, min_q={self.min_q_improvement:.3f}"
        )
