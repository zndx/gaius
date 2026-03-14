"""Outer loop calibration using external frontier models.

Provides external validation of intrinsic verification results using
frontier models (Cerebras API preferred, XAI Grok as fallback). This
ensures the intrinsic verification doesn't drift from human expectations.

Architecture:
    Intrinsic Loop (Inner):
        Agent → KB Oracle → Intrinsic Score → Training Signal

    Calibration Loop (Outer):
        Held-out Tasks → Intrinsic Score ───┐
                                            ├─→ Correlation Analysis → Drift Detection
        Held-out Tasks → External Score ────┘

The calibration loop runs periodically (not every cycle) to:
1. Validate intrinsic scores against frontier model judgments
2. Detect score drift or calibration issues
3. Adjust reward strategies if needed

Usage:
    calibrator = CalibrationOracle(prefer_cerebras=True)

    # Run calibration on held-out tasks
    result = await calibrator.run_calibration(held_out_tasks)

    # Check for drift
    if result.drift_detected:
        logger.warning(f"Score drift: {result.correlation:.2f}")
"""

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class CalibrationResult:
    """Result from a calibration run."""

    # Tasks evaluated
    tasks_evaluated: int = 0
    tasks_succeeded: int = 0

    # Score comparison
    intrinsic_scores: list[float] = field(default_factory=list)
    external_scores: list[float] = field(default_factory=list)

    # Correlation metrics
    correlation: float = 0.0
    mean_absolute_error: float = 0.0
    bias: float = 0.0  # Positive = intrinsic scores too high

    # Drift detection
    drift_detected: bool = False
    drift_severity: str = "none"  # none, mild, moderate, severe

    # External model info
    external_provider: str = ""  # cerebras or xai
    external_model: str = ""

    # Timing
    duration_ms: int = 0
    calibrated_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "tasks_evaluated": self.tasks_evaluated,
            "tasks_succeeded": self.tasks_succeeded,
            "correlation": self.correlation,
            "mean_absolute_error": self.mean_absolute_error,
            "bias": self.bias,
            "drift_detected": self.drift_detected,
            "drift_severity": self.drift_severity,
            "external_provider": self.external_provider,
            "external_model": self.external_model,
            "duration_ms": self.duration_ms,
            "calibrated_at": self.calibrated_at.isoformat(),
        }


@dataclass
class CalibrationConfig:
    """Configuration for calibration oracle."""

    # Provider preferences
    prefer_cerebras: bool = True  # Use Cerebras first, XAI as fallback

    # Scoring thresholds
    min_correlation: float = 0.7  # Below this = drift warning
    severe_drift_threshold: float = 0.5  # Below this = severe drift

    # Bias thresholds
    max_bias: float = 0.15  # Intrinsic vs external score difference

    # Rate limiting
    max_calibrations_per_day: int = 5
    cooldown_hours: float = 4.0  # Minimum hours between calibrations

    # Sample size
    min_sample_size: int = 10
    max_sample_size: int = 50


class CalibrationOracle:
    """External validation oracle for calibration loop.

    Uses frontier models (Cerebras open weights, XAI Grok) to validate
    intrinsic verification scores. This ensures the intrinsic loop
    remains calibrated to human expectations.

    Design principles:
    1. Intrinsic first - always compute intrinsic score
    2. External validation - compare with frontier model judgment
    3. Correlation tracking - detect drift over time
    4. Budget-aware - use XAI sparingly (frontier model budget)
    """

    def __init__(
        self,
        config: CalibrationConfig | None = None,
    ):
        """Initialize calibration oracle.

        Args:
            config: Calibration configuration
        """
        self.config = config or CalibrationConfig()
        self._last_calibration: datetime | None = None
        self._daily_count = 0
        self._daily_reset: datetime | None = None

    async def run_calibration(
        self,
        held_out_tasks: list,  # List[TaskItem]
        intrinsic_scores: list[float],
    ) -> CalibrationResult:
        """Run calibration against external model.

        Args:
            held_out_tasks: Tasks to evaluate
            intrinsic_scores: Corresponding intrinsic scores

        Returns:
            CalibrationResult with correlation metrics
        """
        import time
        start_time = time.time()

        # Check rate limiting
        if not self._can_run_calibration():
            return CalibrationResult(
                drift_severity="rate_limited",
            )

        # Limit sample size
        sample_size = min(len(held_out_tasks), self.config.max_sample_size)
        if sample_size < self.config.min_sample_size:
            return CalibrationResult(
                drift_severity="insufficient_samples",
            )

        tasks = held_out_tasks[:sample_size]
        intrinsic = intrinsic_scores[:sample_size]

        # Get external scores
        external_scores = []
        provider = ""
        model = ""

        for task in tasks:
            score, prov, mod = await self._get_external_score(task)
            external_scores.append(score)
            if not provider:
                provider = prov
                model = mod

        # Compute correlation
        correlation = self._compute_correlation(intrinsic, external_scores)
        mae = self._compute_mae(intrinsic, external_scores)
        bias = self._compute_bias(intrinsic, external_scores)

        # Detect drift
        drift_detected, drift_severity = self._detect_drift(correlation, bias)

        # Update tracking
        self._last_calibration = datetime.now()
        self._daily_count += 1

        duration_ms = int((time.time() - start_time) * 1000)

        result = CalibrationResult(
            tasks_evaluated=len(tasks),
            tasks_succeeded=len([s for s in external_scores if s is not None]),
            intrinsic_scores=intrinsic,
            external_scores=external_scores,
            correlation=correlation,
            mean_absolute_error=mae,
            bias=bias,
            drift_detected=drift_detected,
            drift_severity=drift_severity,
            external_provider=provider,
            external_model=model,
            duration_ms=duration_ms,
        )

        logger.info(
            f"Calibration complete: correlation={correlation:.2f}, "
            f"bias={bias:+.2f}, drift={drift_severity}"
        )

        return result

    def _can_run_calibration(self) -> bool:
        """Check if we can run a calibration (rate limiting)."""
        now = datetime.now()

        # Reset daily count
        if self._daily_reset is None or (now - self._daily_reset).days >= 1:
            self._daily_reset = now
            self._daily_count = 0

        # Check daily limit
        if self._daily_count >= self.config.max_calibrations_per_day:
            logger.info("Calibration rate limited (daily)")
            return False

        # Check cooldown
        if self._last_calibration:
            hours_since = (now - self._last_calibration).total_seconds() / 3600
            if hours_since < self.config.cooldown_hours:
                logger.info(f"Calibration cooldown ({hours_since:.1f}h < {self.config.cooldown_hours}h)")
                return False

        return True

    async def _get_external_score(
        self,
        task,  # TaskItem
    ) -> tuple[float, str, str]:
        """Get score from external model.

        Returns:
            Tuple of (score, provider, model)
        """
        # Try Cerebras first if preferred
        if self.config.prefer_cerebras:
            score, model = await self._score_with_cerebras(task)
            if score is not None:
                return score, "cerebras", model

        # Fall back to XAI
        score, model = await self._score_with_xai(task)
        if score is not None:
            return score, "xai", model

        # Both failed
        return 0.5, "none", ""

    async def _score_with_cerebras(
        self,
        task,  # TaskItem
    ) -> tuple[float | None, str]:
        """Score task using Cerebras API.

        Returns:
            Tuple of (score, model_name) or (None, "") if failed
        """
        try:
            # Use Cerebras endpoint via optillm passthrough
            import httpx
            import json

            # Get Cerebras API key
            api_key = os.environ.get("CEREBRAS_API_KEY", "")
            if not api_key:
                logger.debug("Cerebras API key not configured")
                return None, ""

            prompt = self._build_scoring_prompt(task)

            async with httpx.AsyncClient() as client:
                response = await client.post(
                    "https://api.cerebras.ai/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": "llama3.1-70b",  # Fast open weights model
                        "messages": [{"role": "user", "content": prompt}],
                        "max_tokens": 100,
                        "temperature": 0.0,
                    },
                    timeout=30.0,
                )

                if response.status_code == 200:
                    data = response.json()
                    content = data["choices"][0]["message"]["content"]
                    score = self._parse_score(content)
                    return score, "llama3.1-70b"

            return None, ""

        except Exception as e:
            logger.debug(f"Cerebras scoring failed: {e}")
            return None, ""

    async def _score_with_xai(
        self,
        task,  # TaskItem
    ) -> tuple[float | None, str]:
        """Score task using XAI Grok API.

        Returns:
            Tuple of (score, model_name) or (None, "") if failed
        """
        try:
            # Check XAI budget first
            from gaius.models.xai_budget import check_xai_budget

            if not check_xai_budget("calibration"):
                logger.debug("XAI budget exhausted for calibration")
                return None, ""

            import httpx
            import json

            from gaius.core.config import get_config

            api_key = get_config().providers.xai.api_key
            if not api_key:
                logger.debug("XAI API key not configured")
                return None, ""

            prompt = self._build_scoring_prompt(task)

            async with httpx.AsyncClient() as client:
                response = await client.post(
                    "https://api.x.ai/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": "grok-3-mini-fast",
                        "messages": [{"role": "user", "content": prompt}],
                        "max_tokens": 100,
                        "temperature": 0.0,
                    },
                    timeout=30.0,
                )

                if response.status_code == 200:
                    # Record XAI usage
                    from gaius.models.xai_budget import record_xai_usage
                    record_xai_usage("calibration", 1)

                    data = response.json()
                    content = data["choices"][0]["message"]["content"]
                    score = self._parse_score(content)
                    return score, "grok-3-mini-fast"

            return None, ""

        except Exception as e:
            logger.debug(f"XAI scoring failed: {e}")
            return None, ""

    def _build_scoring_prompt(self, task) -> str:
        """Build scoring prompt for external model."""
        return f"""Rate the quality of this task completion on a scale of 0-100.

TASK:
{task.prompt[:1000]}

{f"EXPECTED OUTPUT: {task.expected_output[:500]}" if task.expected_output else ""}

Respond with just a number 0-100."""

    def _parse_score(self, content: str) -> float:
        """Parse score from model response."""
        import re

        # Find number in response
        match = re.search(r'(\d+)', content)
        if match:
            score = int(match.group(1))
            # Normalize to 0-1
            return min(1.0, max(0.0, score / 100))

        return 0.5  # Default

    def _compute_correlation(
        self,
        intrinsic: list[float],
        external: list[float],
    ) -> float:
        """Compute Pearson correlation between score lists."""
        if len(intrinsic) < 3 or len(external) < 3:
            return 0.0

        try:
            import statistics

            n = len(intrinsic)
            mean_i = statistics.mean(intrinsic)
            mean_e = statistics.mean(external)

            numerator = sum(
                (intrinsic[i] - mean_i) * (external[i] - mean_e)
                for i in range(n)
            )

            var_i = sum((x - mean_i) ** 2 for x in intrinsic)
            var_e = sum((x - mean_e) ** 2 for x in external)

            if var_i == 0 or var_e == 0:
                return 0.0

            denominator = (var_i * var_e) ** 0.5
            return numerator / denominator

        except Exception:
            return 0.0

    def _compute_mae(
        self,
        intrinsic: list[float],
        external: list[float],
    ) -> float:
        """Compute mean absolute error."""
        if not intrinsic or not external:
            return 0.0

        n = min(len(intrinsic), len(external))
        return sum(abs(intrinsic[i] - external[i]) for i in range(n)) / n

    def _compute_bias(
        self,
        intrinsic: list[float],
        external: list[float],
    ) -> float:
        """Compute bias (positive = intrinsic scores too high)."""
        if not intrinsic or not external:
            return 0.0

        n = min(len(intrinsic), len(external))
        return sum(intrinsic[i] - external[i] for i in range(n)) / n

    def _detect_drift(
        self,
        correlation: float,
        bias: float,
    ) -> tuple[bool, str]:
        """Detect score drift.

        Returns:
            Tuple of (drift_detected, severity)
        """
        if correlation < self.config.severe_drift_threshold:
            return True, "severe"

        if correlation < self.config.min_correlation:
            return True, "moderate"

        if abs(bias) > self.config.max_bias:
            return True, "mild"

        return False, "none"


# Singleton instance
_calibration_oracle: CalibrationOracle | None = None


def get_calibration_oracle(
    config: CalibrationConfig | None = None,
) -> CalibrationOracle:
    """Get or create calibration oracle singleton.

    Args:
        config: Calibration config (only used on first call)

    Returns:
        CalibrationOracle instance
    """
    global _calibration_oracle
    if _calibration_oracle is None:
        _calibration_oracle = CalibrationOracle(config)
    return _calibration_oracle


__all__ = [
    "CalibrationResult",
    "CalibrationConfig",
    "CalibrationOracle",
    "get_calibration_oracle",
]
