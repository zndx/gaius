"""Tiered evaluation with local-first strategy and XAI budget management.

Uses local reasoning model (QwQ) for routine evaluation, reserves XAI Grok
for strategic use cases:
- Daily spot checks (sample of held-out queries)
- Version promotion decisions
- Disagreement resolution (local vs training divergence)

Budget tracking ensures XAI credits aren't exhausted.
"""

import asyncio
import hashlib
import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, date, timedelta
from typing import Optional, Literal

from .evaluation import (
    EvaluationResult,
    EvaluationDimension,
    DimensionScore,
    XAIEvaluator,
)

logger = logging.getLogger(__name__)


@dataclass
class EvalBudget:
    """XAI evaluation budget tracking."""

    daily_limit: int = 50  # Max XAI evals per day
    weekly_limit: int = 200  # Max XAI evals per week
    daily_used: int = 0
    weekly_used: int = 0
    last_daily_reset: date = field(default_factory=date.today)
    last_weekly_reset: date = field(default_factory=date.today)
    total_tokens_used: int = 0

    def can_use_xai(self) -> bool:
        """Check if we have budget for XAI eval."""
        self._maybe_reset()
        return self.daily_used < self.daily_limit and self.weekly_used < self.weekly_limit

    def record_use(self, tokens: int = 0) -> None:
        """Record an XAI evaluation use."""
        self._maybe_reset()
        self.daily_used += 1
        self.weekly_used += 1
        self.total_tokens_used += tokens

    def _maybe_reset(self) -> None:
        """Reset counters if new day/week."""
        today = date.today()

        if today > self.last_daily_reset:
            self.daily_used = 0
            self.last_daily_reset = today

        # Reset weekly on Monday
        if today > self.last_weekly_reset + timedelta(days=7):
            self.weekly_used = 0
            self.last_weekly_reset = today

    @property
    def remaining_daily(self) -> int:
        """Remaining daily budget."""
        self._maybe_reset()
        return max(0, self.daily_limit - self.daily_used)

    @property
    def remaining_weekly(self) -> int:
        """Remaining weekly budget."""
        self._maybe_reset()
        return max(0, self.weekly_limit - self.weekly_used)


@dataclass
class TieredEvalConfig:
    """Configuration for tiered evaluation."""

    # XAI budget
    daily_xai_limit: int = 50
    weekly_xai_limit: int = 200

    # Spot check settings
    spot_check_sample_size: int = 5  # How many to send to XAI per daily eval
    spot_check_threshold: float = 0.15  # Local-XAI score divergence threshold

    # When to use XAI
    use_xai_for_promotion: bool = True  # Always use XAI for version promotion
    use_xai_for_disagreement: bool = True  # Use XAI when local diverges from training
    disagreement_threshold: float = 0.20  # Score difference to trigger XAI

    # Local model settings
    local_model: str = ""  # Empty = use default reasoning model


class LocalEvaluator:
    """Evaluator using local reasoning model (QwQ/Orchestrator).

    Provides fast, free evaluation for routine assessment.
    Less sophisticated than XAI but good for filtering.
    """

    def __init__(self, model: str = ""):
        """Initialize local evaluator.

        Args:
            model: Model to use (empty = default reasoning)
        """
        self.model = model

    async def evaluate(
        self,
        agent_output: str,
        task_prompt: str,
        context: str = "",
        dimensions: list[EvaluationDimension] | None = None,
    ) -> EvaluationResult:
        """Evaluate using local reasoning model.

        Args:
            agent_output: Output to evaluate
            task_prompt: Original task
            context: Additional context
            dimensions: Dimensions to evaluate

        Returns:
            EvaluationResult
        """
        import time

        start = time.perf_counter()

        if dimensions is None:
            dimensions = [
                EvaluationDimension.ACCURACY,
                EvaluationDimension.COHERENCE,
                EvaluationDimension.RELEVANCE,
            ]

        # Build simple evaluation prompt
        prompt = self._build_prompt(agent_output, task_prompt, context, dimensions)

        try:
            # Try to use local inference
            from ..inference.scheduler import get_scheduler_service

            scheduler = get_scheduler_service()
            result = await scheduler.submit_job(
                prompt=prompt,
                system_prompt=self._system_prompt(),
                model=self.model or "",  # Empty uses default
                max_tokens=1024,
                priority="low",
            )

            content = result.get("output", "")
            tokens = result.get("tokens", 0)

        except Exception as e:
            logger.warning(f"Local eval failed, using heuristic: {e}")
            return self._heuristic_eval(agent_output, task_prompt, dimensions)

        latency_ms = int((time.perf_counter() - start) * 1000)

        # Parse response
        eval_result = self._parse_response(content, dimensions)
        eval_result.evaluator_model = f"local:{self.model or 'default'}"
        eval_result.tokens_used = tokens
        eval_result.latency_ms = latency_ms

        return eval_result

    def _system_prompt(self) -> str:
        """System prompt for local evaluation."""
        return """You are evaluating an AI agent's output. Be concise but thorough.

Rate each dimension 0-1 and provide brief feedback. Respond in JSON:
{
    "overall_score": 0.0-1.0,
    "dimension_scores": {
        "dimension_name": {"score": 0.0-1.0, "feedback": "brief feedback"}
    },
    "summary": "one sentence overall"
}"""

    def _build_prompt(
        self,
        agent_output: str,
        task_prompt: str,
        context: str,
        dimensions: list[EvaluationDimension],
    ) -> str:
        """Build evaluation prompt."""
        dim_list = ", ".join(d.value for d in dimensions)

        return f"""Evaluate this agent output.

TASK: {task_prompt[:500]}

OUTPUT: {agent_output[:1000]}

CONTEXT: {context[:300] if context else "None"}

Evaluate dimensions: {dim_list}

Respond with JSON scores (0-1) for each dimension."""

    def _parse_response(
        self,
        content: str,
        dimensions: list[EvaluationDimension],
    ) -> EvaluationResult:
        """Parse local model response."""
        try:
            # Extract JSON
            if "```json" in content:
                json_str = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                json_str = content.split("```")[1].split("```")[0].strip()
            else:
                # Try to find JSON object
                start = content.find("{")
                end = content.rfind("}") + 1
                if start >= 0 and end > start:
                    json_str = content[start:end]
                else:
                    json_str = content

            data = json.loads(json_str)

            result = EvaluationResult(
                overall_score=float(data.get("overall_score", 0.5)),
                summary=data.get("summary", ""),
            )

            for dim_name, score_data in data.get("dimension_scores", {}).items():
                try:
                    dim = EvaluationDimension(dim_name)
                    if dim in dimensions:
                        result.dimension_scores[dim] = DimensionScore(
                            dimension=dim,
                            score=float(score_data.get("score", 0.5)),
                            feedback=score_data.get("feedback", ""),
                        )
                except ValueError:
                    continue

            return result

        except Exception:
            # Fallback
            return EvaluationResult(overall_score=0.5, summary="Parse error")

    def _heuristic_eval(
        self,
        agent_output: str,
        task_prompt: str,
        dimensions: list[EvaluationDimension],
    ) -> EvaluationResult:
        """Simple heuristic evaluation when inference fails."""
        # Basic heuristics
        output_len = len(agent_output)
        prompt_len = len(task_prompt)

        # Length-based score (very rough)
        if output_len < 50:
            base_score = 0.3
        elif output_len < 200:
            base_score = 0.5
        elif output_len < 1000:
            base_score = 0.6
        else:
            base_score = 0.65

        result = EvaluationResult(
            overall_score=base_score,
            summary="Heuristic evaluation (inference unavailable)",
            evaluator_model="heuristic",
        )

        for dim in dimensions:
            result.dimension_scores[dim] = DimensionScore(
                dimension=dim,
                score=base_score,
                feedback="Heuristic score",
            )

        return result


class TieredEvaluator:
    """Tiered evaluation with local-first strategy.

    Uses local model for routine evaluation, XAI for strategic decisions.
    Tracks budget to avoid exhausting XAI credits.
    """

    def __init__(self, config: TieredEvalConfig | None = None):
        """Initialize tiered evaluator.

        Args:
            config: Configuration (uses defaults if None)
        """
        self.config = config or TieredEvalConfig()
        self.budget = EvalBudget(
            daily_limit=self.config.daily_xai_limit,
            weekly_limit=self.config.weekly_xai_limit,
        )
        self.local = LocalEvaluator(model=self.config.local_model)
        self._xai: XAIEvaluator | None = None
        self._cache: dict[str, EvaluationResult] = {}

    @property
    def xai(self) -> XAIEvaluator | None:
        """Lazy-load XAI evaluator."""
        if self._xai is None:
            try:
                self._xai = XAIEvaluator()
            except ValueError:
                logger.warning("XAI API key not configured")
        return self._xai

    def _cache_key(self, output: str, prompt: str) -> str:
        """Generate cache key for an evaluation."""
        content = f"{output[:500]}|{prompt[:200]}"
        return hashlib.sha256(content.encode()).hexdigest()[:16]

    async def evaluate(
        self,
        agent_output: str,
        task_prompt: str,
        context: str = "",
        dimensions: list[EvaluationDimension] | None = None,
        use_tier: Literal["local", "xai", "auto"] = "auto",
        force_xai: bool = False,
    ) -> EvaluationResult:
        """Evaluate with tiered strategy.

        Args:
            agent_output: Output to evaluate
            task_prompt: Original task
            context: Additional context
            dimensions: Dimensions to evaluate
            use_tier: Which tier to use (auto = decide based on budget/strategy)
            force_xai: Force XAI even if over budget (for critical evals)

        Returns:
            EvaluationResult
        """
        # Check cache
        cache_key = self._cache_key(agent_output, task_prompt)
        if cache_key in self._cache:
            cached = self._cache[cache_key]
            cached.summary = f"[cached] {cached.summary}"
            return cached

        # Decide which tier
        if use_tier == "local":
            result = await self.local.evaluate(
                agent_output, task_prompt, context, dimensions
            )
        elif use_tier == "xai":
            result = await self._xai_evaluate(
                agent_output, task_prompt, context, dimensions, force_xai
            )
        else:  # auto
            result = await self._auto_evaluate(
                agent_output, task_prompt, context, dimensions
            )

        # Cache result
        self._cache[cache_key] = result

        # Limit cache size
        if len(self._cache) > 1000:
            # Remove oldest entries
            keys = list(self._cache.keys())[:500]
            for k in keys:
                del self._cache[k]

        return result

    async def _auto_evaluate(
        self,
        agent_output: str,
        task_prompt: str,
        context: str,
        dimensions: list[EvaluationDimension] | None,
    ) -> EvaluationResult:
        """Auto-decide which tier to use."""
        # Always start with local
        local_result = await self.local.evaluate(
            agent_output, task_prompt, context, dimensions
        )

        # Check if XAI is needed and available
        if not self.budget.can_use_xai() or self.xai is None:
            return local_result

        # Don't use XAI for clearly good or bad outputs
        if local_result.overall_score > 0.85 or local_result.overall_score < 0.25:
            return local_result

        # Use XAI for borderline cases (randomly sample to stay in budget)
        import random
        if random.random() > 0.1:  # 10% chance for borderline
            return local_result

        # Run XAI for comparison
        xai_result = await self._xai_evaluate(
            agent_output, task_prompt, context, dimensions, force=False
        )

        if xai_result:
            return xai_result
        return local_result

    async def _xai_evaluate(
        self,
        agent_output: str,
        task_prompt: str,
        context: str,
        dimensions: list[EvaluationDimension] | None,
        force: bool = False,
    ) -> EvaluationResult | None:
        """Evaluate with XAI (budget-aware)."""
        if not force and not self.budget.can_use_xai():
            logger.info("XAI budget exhausted, skipping")
            return None

        if self.xai is None:
            return None

        try:
            result = await self.xai.evaluate(
                agent_output=agent_output,
                task_prompt=task_prompt,
                context=context,
                dimensions=dimensions,
            )

            self.budget.record_use(result.tokens_used)
            return result

        except Exception as e:
            logger.warning(f"XAI evaluation failed: {e}")
            return None

    async def spot_check_batch(
        self,
        evaluations: list[dict],
        sample_size: int | None = None,
    ) -> list[tuple[EvaluationResult, EvaluationResult | None]]:
        """Run batch evaluation with XAI spot checks.

        Evaluates all with local, samples subset for XAI comparison.

        Args:
            evaluations: List of {agent_output, task_prompt, context, dimensions}
            sample_size: How many to spot check with XAI (None = use config)

        Returns:
            List of (local_result, xai_result or None) tuples
        """
        import random

        sample_size = sample_size or self.config.spot_check_sample_size

        # Evaluate all with local
        local_results = await asyncio.gather(*[
            self.local.evaluate(
                e["agent_output"],
                e["task_prompt"],
                e.get("context", ""),
                e.get("dimensions"),
            )
            for e in evaluations
        ])

        # Select sample for XAI spot check
        indices = list(range(len(evaluations)))
        random.shuffle(indices)
        spot_check_indices = set(indices[:min(sample_size, len(indices))])

        # Only spot check if we have budget
        xai_results: list[EvaluationResult | None] = [None] * len(evaluations)

        if self.xai and self.budget.remaining_daily >= sample_size:
            for i in spot_check_indices:
                e = evaluations[i]
                xai_result = await self._xai_evaluate(
                    e["agent_output"],
                    e["task_prompt"],
                    e.get("context", ""),
                    e.get("dimensions"),
                    force=False,
                )
                xai_results[i] = xai_result

        return list(zip(local_results, xai_results))

    async def evaluate_for_promotion(
        self,
        agent_output: str,
        task_prompt: str,
        context: str = "",
        local_score: float | None = None,
    ) -> EvaluationResult:
        """Evaluate for version promotion decision.

        Always uses XAI if configured and available.

        Args:
            agent_output: Output to evaluate
            task_prompt: Task prompt
            context: Context
            local_score: Optional local score for comparison

        Returns:
            EvaluationResult (XAI if available, else local)
        """
        if self.config.use_xai_for_promotion and self.xai:
            result = await self._xai_evaluate(
                agent_output, task_prompt, context, None, force=True
            )
            if result:
                return result

        # Fallback to local
        return await self.local.evaluate(agent_output, task_prompt, context)

    def get_budget_status(self) -> dict:
        """Get current budget status."""
        return {
            "daily_used": self.budget.daily_used,
            "daily_limit": self.budget.daily_limit,
            "daily_remaining": self.budget.remaining_daily,
            "weekly_used": self.budget.weekly_used,
            "weekly_limit": self.budget.weekly_limit,
            "weekly_remaining": self.budget.remaining_weekly,
            "total_tokens": self.budget.total_tokens_used,
            "xai_available": self.xai is not None,
        }


# Module-level singleton
_tiered_evaluator: TieredEvaluator | None = None


def get_tiered_evaluator(config: TieredEvalConfig | None = None) -> TieredEvaluator:
    """Get or create tiered evaluator singleton."""
    global _tiered_evaluator
    if _tiered_evaluator is None:
        _tiered_evaluator = TieredEvaluator(config)
    return _tiered_evaluator


async def evaluate_with_budget(
    agent_output: str,
    task_prompt: str,
    context: str = "",
    use_tier: Literal["local", "xai", "auto"] = "auto",
) -> EvaluationResult:
    """Convenience function for budget-aware evaluation."""
    evaluator = get_tiered_evaluator()
    return await evaluator.evaluate(
        agent_output=agent_output,
        task_prompt=task_prompt,
        context=context,
        use_tier=use_tier,
    )
