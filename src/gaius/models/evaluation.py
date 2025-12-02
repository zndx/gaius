"""xAI Grok evaluation for agent output assessment.

Uses frontier model (Grok-2) to evaluate agent outputs across multiple
dimensions, providing feedback for agent refinement.

Usage:
    from gaius.models import evaluate_output, EvaluationDimension

    result = await evaluate_output(
        agent_output="...",
        task_prompt="...",
        context="...",
        dimensions=[EvaluationDimension.ACCURACY, EvaluationDimension.COHERENCE],
    )

    print(f"Overall score: {result.overall_score}")
    for dim, score in result.dimension_scores.items():
        print(f"  {dim.value}: {score.score} - {score.feedback}")
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any
import os
import json


class EvaluationDimension(Enum):
    """Dimensions for evaluating agent output."""

    ACCURACY = "accuracy"  # Factual correctness
    COHERENCE = "coherence"  # Logical flow and structure
    RELEVANCE = "relevance"  # Alignment with task/prompt
    COMPLETENESS = "completeness"  # Coverage of requirements
    CLARITY = "clarity"  # Ease of understanding
    ACTIONABILITY = "actionability"  # Practical usefulness
    CREATIVITY = "creativity"  # Novel insights or approaches
    SAFETY = "safety"  # Absence of harmful content


@dataclass
class DimensionScore:
    """Score for a single evaluation dimension."""

    dimension: EvaluationDimension
    score: float  # 0-1
    feedback: str  # Specific feedback
    suggestions: list[str] = field(default_factory=list)


@dataclass
class EvaluationResult:
    """Complete evaluation result from frontier model."""

    # Scores
    overall_score: float  # 0-1 weighted average
    dimension_scores: dict[EvaluationDimension, DimensionScore] = field(
        default_factory=dict
    )

    # Feedback
    summary: str = ""  # Overall assessment
    strengths: list[str] = field(default_factory=list)
    weaknesses: list[str] = field(default_factory=list)
    improvement_suggestions: list[str] = field(default_factory=list)

    # Metadata
    evaluator_model: str = ""
    evaluation_time: datetime = field(default_factory=datetime.now)
    tokens_used: int = 0
    latency_ms: int = 0

    # Context
    agent_id: str | None = None
    agent_version: str | None = None
    task_type: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for storage."""
        return {
            "overall_score": self.overall_score,
            "dimension_scores": {
                dim.value: {
                    "score": score.score,
                    "feedback": score.feedback,
                    "suggestions": score.suggestions,
                }
                for dim, score in self.dimension_scores.items()
            },
            "summary": self.summary,
            "strengths": self.strengths,
            "weaknesses": self.weaknesses,
            "improvement_suggestions": self.improvement_suggestions,
            "evaluator_model": self.evaluator_model,
            "evaluation_time": self.evaluation_time.isoformat(),
            "tokens_used": self.tokens_used,
            "latency_ms": self.latency_ms,
            "agent_id": self.agent_id,
            "agent_version": self.agent_version,
            "task_type": self.task_type,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "EvaluationResult":
        """Create from dictionary."""
        result = cls(
            overall_score=data["overall_score"],
            summary=data.get("summary", ""),
            strengths=data.get("strengths", []),
            weaknesses=data.get("weaknesses", []),
            improvement_suggestions=data.get("improvement_suggestions", []),
            evaluator_model=data.get("evaluator_model", ""),
            tokens_used=data.get("tokens_used", 0),
            latency_ms=data.get("latency_ms", 0),
            agent_id=data.get("agent_id"),
            agent_version=data.get("agent_version"),
            task_type=data.get("task_type"),
        )

        if "evaluation_time" in data:
            result.evaluation_time = datetime.fromisoformat(data["evaluation_time"])

        for dim_name, score_data in data.get("dimension_scores", {}).items():
            dim = EvaluationDimension(dim_name)
            result.dimension_scores[dim] = DimensionScore(
                dimension=dim,
                score=score_data["score"],
                feedback=score_data["feedback"],
                suggestions=score_data.get("suggestions", []),
            )

        return result


class XAIEvaluator:
    """Evaluator using xAI Grok-2 for frontier model assessment."""

    DEFAULT_MODEL = "grok-2-latest"
    API_BASE = "https://api.x.ai/v1"

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
    ):
        """Initialize xAI evaluator.

        Args:
            api_key: xAI API key (defaults to XAI_API_KEY env var)
            model: Model to use (defaults to grok-2-latest)
        """
        self.api_key = api_key or os.getenv("XAI_API_KEY")
        self.model = model or self.DEFAULT_MODEL

        if not self.api_key:
            raise ValueError(
                "xAI API key required. Set XAI_API_KEY environment variable."
            )

    async def evaluate(
        self,
        agent_output: str,
        task_prompt: str,
        context: str = "",
        dimensions: list[EvaluationDimension] | None = None,
        agent_id: str | None = None,
        agent_version: str | None = None,
        task_type: str | None = None,
    ) -> EvaluationResult:
        """Evaluate agent output using Grok-2.

        Args:
            agent_output: The output to evaluate
            task_prompt: Original task/prompt given to agent
            context: Additional context (KB excerpts, etc.)
            dimensions: Which dimensions to evaluate (default: all)
            agent_id: Optional agent identifier
            agent_version: Optional agent version
            task_type: Optional task type identifier

        Returns:
            EvaluationResult with scores and feedback
        """
        import time
        import httpx

        start = time.perf_counter()

        if dimensions is None:
            dimensions = list(EvaluationDimension)

        # Build evaluation prompt
        eval_prompt = self._build_eval_prompt(
            agent_output, task_prompt, context, dimensions
        )

        # Call xAI API
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.API_BASE}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "messages": [
                        {
                            "role": "system",
                            "content": self._system_prompt(),
                        },
                        {
                            "role": "user",
                            "content": eval_prompt,
                        },
                    ],
                    "temperature": 0.3,  # Lower for consistent evaluation
                    "max_tokens": 2048,
                },
                timeout=60.0,
            )

            response.raise_for_status()
            data = response.json()

        latency_ms = int((time.perf_counter() - start) * 1000)

        # Parse response
        content = data["choices"][0]["message"]["content"]
        tokens = data.get("usage", {}).get("total_tokens", 0)

        result = self._parse_evaluation(content, dimensions)
        result.evaluator_model = self.model
        result.tokens_used = tokens
        result.latency_ms = latency_ms
        result.agent_id = agent_id
        result.agent_version = agent_version
        result.task_type = task_type

        return result

    def _system_prompt(self) -> str:
        """System prompt for evaluation."""
        return """You are an expert evaluator assessing AI agent outputs.
Your role is to provide objective, constructive evaluation across multiple dimensions.

Always respond with valid JSON in this exact format:
{
    "overall_score": 0.0-1.0,
    "summary": "Brief overall assessment",
    "dimension_scores": {
        "dimension_name": {
            "score": 0.0-1.0,
            "feedback": "Specific feedback for this dimension",
            "suggestions": ["Improvement suggestion 1", "..."]
        }
    },
    "strengths": ["Strength 1", "Strength 2"],
    "weaknesses": ["Weakness 1", "Weakness 2"],
    "improvement_suggestions": ["Overall suggestion 1", "Overall suggestion 2"]
}

Be rigorous but fair. Scores should reflect actual quality:
- 0.9-1.0: Excellent, minimal to no issues
- 0.7-0.89: Good, minor issues
- 0.5-0.69: Acceptable, notable issues
- 0.3-0.49: Poor, significant issues
- 0.0-0.29: Very poor, fundamental problems"""

    def _build_eval_prompt(
        self,
        agent_output: str,
        task_prompt: str,
        context: str,
        dimensions: list[EvaluationDimension],
    ) -> str:
        """Build the evaluation prompt."""
        dim_descriptions = {
            EvaluationDimension.ACCURACY: "Factual correctness and precision",
            EvaluationDimension.COHERENCE: "Logical flow, structure, and consistency",
            EvaluationDimension.RELEVANCE: "Alignment with the original task/prompt",
            EvaluationDimension.COMPLETENESS: "Coverage of all requirements",
            EvaluationDimension.CLARITY: "Ease of understanding and communication",
            EvaluationDimension.ACTIONABILITY: "Practical usefulness and applicability",
            EvaluationDimension.CREATIVITY: "Novel insights or approaches",
            EvaluationDimension.SAFETY: "Absence of harmful or problematic content",
        }

        dim_list = "\n".join(
            f"- {d.value}: {dim_descriptions[d]}" for d in dimensions
        )

        prompt = f"""Evaluate the following agent output.

## Task/Prompt Given to Agent
{task_prompt}

## Context Provided
{context if context else "(No additional context)"}

## Agent Output to Evaluate
{agent_output}

## Evaluation Dimensions
{dim_list}

Provide your evaluation as JSON with scores (0-1) and specific feedback for each dimension.
Include overall assessment, strengths, weaknesses, and improvement suggestions."""

        return prompt

    def _parse_evaluation(
        self,
        content: str,
        dimensions: list[EvaluationDimension],
    ) -> EvaluationResult:
        """Parse evaluation response from Grok."""
        # Extract JSON from response
        try:
            # Try to find JSON in the response
            if "```json" in content:
                json_str = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                json_str = content.split("```")[1].split("```")[0].strip()
            else:
                json_str = content.strip()

            data = json.loads(json_str)

        except (json.JSONDecodeError, IndexError):
            # Fallback: create minimal result
            return EvaluationResult(
                overall_score=0.5,
                summary=f"Failed to parse evaluation: {content[:200]}",
            )

        result = EvaluationResult(
            overall_score=float(data.get("overall_score", 0.5)),
            summary=data.get("summary", ""),
            strengths=data.get("strengths", []),
            weaknesses=data.get("weaknesses", []),
            improvement_suggestions=data.get("improvement_suggestions", []),
        )

        # Parse dimension scores
        for dim_name, score_data in data.get("dimension_scores", {}).items():
            try:
                dim = EvaluationDimension(dim_name)
                if dim in dimensions:
                    result.dimension_scores[dim] = DimensionScore(
                        dimension=dim,
                        score=float(score_data.get("score", 0.5)),
                        feedback=score_data.get("feedback", ""),
                        suggestions=score_data.get("suggestions", []),
                    )
            except ValueError:
                continue

        return result

    async def batch_evaluate(
        self,
        evaluations: list[dict[str, Any]],
    ) -> list[EvaluationResult]:
        """Evaluate multiple outputs.

        Args:
            evaluations: List of dicts with keys:
                - agent_output: str
                - task_prompt: str
                - context: str (optional)
                - dimensions: list[EvaluationDimension] (optional)

        Returns:
            List of EvaluationResult
        """
        import asyncio

        tasks = [
            self.evaluate(
                agent_output=e["agent_output"],
                task_prompt=e["task_prompt"],
                context=e.get("context", ""),
                dimensions=e.get("dimensions"),
                agent_id=e.get("agent_id"),
                agent_version=e.get("agent_version"),
                task_type=e.get("task_type"),
            )
            for e in evaluations
        ]

        return await asyncio.gather(*tasks)


# ═══════════════════════════════════════════════════════════════════════════════
# Module-level API
# ═══════════════════════════════════════════════════════════════════════════════

_evaluator: XAIEvaluator | None = None


def get_evaluator(api_key: str | None = None) -> XAIEvaluator:
    """Get or create the xAI evaluator singleton."""
    global _evaluator
    if _evaluator is None:
        _evaluator = XAIEvaluator(api_key=api_key)
    return _evaluator


async def evaluate_output(
    agent_output: str,
    task_prompt: str,
    context: str = "",
    dimensions: list[EvaluationDimension] | None = None,
    agent_id: str | None = None,
    agent_version: str | None = None,
) -> EvaluationResult:
    """Convenience function to evaluate agent output."""
    evaluator = get_evaluator()
    return await evaluator.evaluate(
        agent_output=agent_output,
        task_prompt=task_prompt,
        context=context,
        dimensions=dimensions,
        agent_id=agent_id,
        agent_version=agent_version,
    )
