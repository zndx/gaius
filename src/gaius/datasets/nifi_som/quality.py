"""Instruction quality scoring using rubric-based evaluation.

Scores instructions on 4 dimensions (local):
- Clarity (30%): Is the instruction unambiguous?
- Naturalness (25%): Does it sound like a real user?
- Specificity (25%): Does it uniquely identify the target?
- Conciseness (20%): Is it appropriately brief?

Also includes 6-dimension XAI rubric calibration:
- Intent Understanding (15%)
- SoM Grounding (20%)
- Action Semantics (20%)
- ToM Trace (15%) - 4/4 for single actions
- Constraints (15%)
- Outcome (15%)

Uses EvalBudget from tiered_evaluation for budget tracking.
"""

import logging
from dataclasses import dataclass
from typing import Optional, TYPE_CHECKING

from .prompts.quality import (
    get_quality_prompt,
    parse_quality_response,
    get_calibration_prompt,
    parse_calibration_response,
)

if TYPE_CHECKING:
    from ...models.tiered_evaluation import EvalBudget

logger = logging.getLogger(__name__)


@dataclass
class QualityScore:
    """Quality score breakdown for an instruction."""

    clarity: float  # 0.0-1.0
    naturalness: float  # 0.0-1.0
    specificity: float  # 0.0-1.0
    conciseness: float  # 0.0-1.0
    overall: float  # Weighted average
    notes: str = ""
    raw_response: str = ""


@dataclass
class CalibrationResult:
    """Result from XAI calibration evaluation."""

    calibration: str  # "too_high", "about_right", "too_low"
    true_score: float  # XAI's score
    delta: float  # Difference from local score
    feedback: str  # Specific improvements
    raw_response: str = ""


class InstructionQualityScorer:
    """Score instruction quality using rubric evaluation.

    Uses a 4-dimension rubric weighted as:
    - Clarity (30%): Clear and unambiguous
    - Naturalness (25%): Sounds like real user input
    - Specificity (25%): Uniquely identifies target
    - Conciseness (20%): Appropriate length

    Usage:
        scorer = InstructionQualityScorer()
        score = await scorer.score(
            instruction="Click on the fetch_pdf processor to download the paper",
            target_name="fetch_pdf",
            target_type="GetHTTP",
        )
        print(f"Overall: {score.overall:.2f}")
        print(f"Clarity: {score.clarity:.2f}")
    """

    def __init__(self, temperature: float = 0.5, max_tokens: int = 512):
        """Initialize the scorer.

        Args:
            temperature: Moderate temperature for consistent scoring
            max_tokens: Maximum tokens for response
        """
        self.temperature = temperature
        self.max_tokens = max_tokens
        self._client = None

    async def _get_client(self):
        """Lazy-load inference client."""
        if self._client is None:
            from gaius.client.engine_client import EngineInferenceClient as InferenceClient
            self._client = InferenceClient()
        return self._client

    async def score(
        self,
        instruction: str,
        target_name: str,
        target_type: str,
    ) -> QualityScore:
        """Score an instruction's quality.

        Args:
            instruction: The instruction to evaluate
            target_name: Name of target UI element
            target_type: Type of target element

        Returns:
            QualityScore with dimension breakdown
        """
        client = await self._get_client()
        from gaius.client.engine_client import Message

        system_prompt, user_prompt = get_quality_prompt(
            instruction=instruction,
            target_name=target_name,
            target_type=target_type,
        )

        messages = [
            Message(role="system", content=system_prompt),
            Message(role="user", content=user_prompt),
        ]

        try:
            result = await client.complete(
                messages=messages,
                technique=None,  # Passthrough - no special technique
                temperature=self.temperature,
                max_tokens=self.max_tokens,
            )

            parsed = parse_quality_response(result.content)

            return QualityScore(
                clarity=parsed["clarity"],
                naturalness=parsed["naturalness"],
                specificity=parsed["specificity"],
                conciseness=parsed["conciseness"],
                overall=parsed["overall"],
                notes=parsed["notes"],
                raw_response=result.content,
            )

        except Exception as e:
            logger.error(f"Quality scoring failed: {e}")
            # Return middle score on failure
            return QualityScore(
                clarity=0.5,
                naturalness=0.5,
                specificity=0.5,
                conciseness=0.5,
                overall=0.5,
                notes=f"Scoring failed: {e}",
            )

    async def score_batch(
        self,
        instructions: list[tuple[str, str, str]],  # (instruction, target_name, target_type)
    ) -> list[QualityScore]:
        """Score a batch of instructions.

        Args:
            instructions: List of (instruction, target_name, target_type) tuples

        Returns:
            List of QualityScore objects
        """
        import asyncio

        tasks = [
            self.score(inst, name, type_)
            for inst, name, type_ in instructions
        ]
        return await asyncio.gather(*tasks)


class XAICalibrator:
    """Calibrate local quality scores against XAI frontier model.

    NOTE: This is the legacy 4-dimension calibrator. For the new 6-dimension
    rubric calibration, use CalibrationOrchestrator from calibration.py.

    Uses EvalBudget from tiered_evaluation.py for proper budget tracking.

    Usage:
        from gaius.models.tiered_evaluation import EvalBudget
        budget = EvalBudget()
        calibrator = XAICalibrator(budget=budget)
        result = await calibrator.calibrate_single(
            instruction="Click on fetch_pdf",
            target_name="fetch_pdf",
            target_type="GetHTTP",
            local_score=0.75,
        )
        print(f"XAI score: {result.true_score:.2f}")
        print(f"Calibration: {result.calibration}")
    """

    def __init__(
        self,
        budget: Optional["EvalBudget"] = None,
        temperature: float = 0.3,
    ):
        """Initialize calibrator.

        Args:
            budget: EvalBudget from tiered_evaluation (creates default if None)
            temperature: Low temperature for consistent evaluation
        """
        if budget is None:
            from ...models.tiered_evaluation import EvalBudget
            budget = EvalBudget()

        self.budget = budget
        self.temperature = temperature
        self._client = None

    async def _get_client(self):
        """Lazy-load inference client."""
        if self._client is None:
            from gaius.client.engine_client import EngineInferenceClient as InferenceClient
            self._client = InferenceClient()
        return self._client

    def _check_budget(self) -> bool:
        """Check if within daily budget."""
        return self.budget.can_use_xai()

    async def calibrate_single(
        self,
        instruction: str,
        target_name: str,
        target_type: str,
        local_score: float,
    ) -> Optional[CalibrationResult]:
        """Get XAI calibration for a single instruction.

        Args:
            instruction: The instruction to evaluate
            target_name: Name of target element
            target_type: Type of target element
            local_score: Score from local model

        Returns:
            CalibrationResult or None if budget exceeded
        """
        if not self._check_budget():
            logger.warning("XAI calibration budget exceeded")
            return None

        client = await self._get_client()
        from gaius.client.engine_client import Message

        system_prompt, user_prompt = get_calibration_prompt(
            instruction=instruction,
            target_name=target_name,
            target_type=target_type,
            local_score=local_score,
        )

        messages = [
            Message(role="system", content=system_prompt),
            Message(role="user", content=user_prompt),
        ]

        try:
            # XAI judge via the engine's external backend lane (Engine-First)
            result = await client.complete(
                messages,
                model="xai",
                temperature=self.temperature,
            )

            # Record budget use
            tokens = result.input_tokens + result.output_tokens
            self.budget.record_use(tokens)

            parsed = parse_calibration_response(result.content)

            return CalibrationResult(
                calibration=parsed["calibration"],
                true_score=parsed["true_score"],
                delta=parsed["delta"] or (parsed["true_score"] - local_score),
                feedback=parsed["feedback"],
                raw_response=result.content,
            )

        except Exception as e:
            logger.error(f"XAI calibration failed: {e}")
            return None

    async def calibrate_stratified(
        self,
        scored_instructions: list[tuple[str, str, str, float]],
        sample_size: int = 20,
    ) -> dict:
        """Calibrate using stratified sampling across score ranges.

        Samples instructions from high, medium, and low score ranges
        to compute calibration factor.

        Args:
            scored_instructions: List of (instruction, target_name, target_type, local_score)
            sample_size: Total samples to evaluate

        Returns:
            Calibration statistics dict
        """
        import random

        # Cap sample size by budget
        sample_size = min(sample_size, self.budget.remaining_daily)

        # Stratify by score range
        high = [(i, n, t, s) for i, n, t, s in scored_instructions if s >= 0.7]
        mid = [(i, n, t, s) for i, n, t, s in scored_instructions if 0.4 <= s < 0.7]
        low = [(i, n, t, s) for i, n, t, s in scored_instructions if s < 0.4]

        # Sample from each stratum
        samples_per_stratum = sample_size // 3
        selected = []
        selected.extend(random.sample(high, min(len(high), samples_per_stratum)))
        selected.extend(random.sample(mid, min(len(mid), samples_per_stratum)))
        selected.extend(random.sample(low, min(len(low), samples_per_stratum)))

        # Evaluate each sample
        results = []
        for instruction, target_name, target_type, local_score in selected:
            if not self.budget.can_use_xai():
                logger.warning("XAI budget exhausted during stratified calibration")
                break

            result = await self.calibrate_single(
                instruction=instruction,
                target_name=target_name,
                target_type=target_type,
                local_score=local_score,
            )
            if result:
                results.append({
                    "local_score": local_score,
                    "xai_score": result.true_score,
                    "delta": result.delta,
                    "calibration": result.calibration,
                })

        if not results:
            return {"error": "No calibration results", "calibration_factor": 1.0}

        # Compute calibration statistics
        avg_delta = sum(r["delta"] for r in results) / len(results)
        too_high_count = sum(1 for r in results if r["calibration"] == "too_high")
        too_low_count = sum(1 for r in results if r["calibration"] == "too_low")
        about_right_count = sum(1 for r in results if r["calibration"] == "about_right")

        # Compute calibration factor
        # If local scores are consistently too high, factor < 1.0
        # If local scores are consistently too low, factor > 1.0
        calibration_factor = 1.0 - (avg_delta * 0.5)  # Damped adjustment
        calibration_factor = max(0.5, min(1.5, calibration_factor))  # Clamp

        return {
            "sample_count": len(results),
            "avg_delta": avg_delta,
            "too_high_count": too_high_count,
            "too_low_count": too_low_count,
            "about_right_count": about_right_count,
            "calibration_factor": calibration_factor,
            "budget_remaining": self.budget.remaining_daily,
            "results": results,
        }

    def get_budget_status(self) -> dict:
        """Get current budget status."""
        return {
            "daily_used": self.budget.daily_used,
            "daily_limit": self.budget.daily_limit,
            "daily_remaining": self.budget.remaining_daily,
            "weekly_used": self.budget.weekly_used,
            "weekly_limit": self.budget.weekly_limit,
            "weekly_remaining": self.budget.remaining_weekly,
        }


def apply_calibration(score: float, calibration_factor: float) -> float:
    """Apply calibration factor to a local score.

    Args:
        score: Local quality score (0.0-1.0)
        calibration_factor: Factor from XAI calibration

    Returns:
        Calibrated score clamped to [0.0, 1.0]
    """
    calibrated = score * calibration_factor
    return max(0.0, min(1.0, calibrated))
