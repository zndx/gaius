"""Evaluation framework for Zettelkasten synthesis quality.

Uses a frontier model (Claude/GPT-4) to judge synthesis quality
across multiple dimensions. Stores results for APO training.

Usage:
    evaluator = SynthesisEvaluator()
    result = await evaluator.evaluate(note, query, sources)

    # Store for APO
    result.save()
"""

import json
import os
import re
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from .synthesis import ZettelkastenNote


@dataclass
class EvaluationDimension:
    """A single evaluation dimension."""

    name: str
    description: str
    weight: float = 1.0


# Standard evaluation dimensions for Zettelkasten synthesis
EVAL_DIMENSIONS = [
    EvaluationDimension(
        name="factual_accuracy",
        description="Claims are supported by provided sources; no hallucinations",
        weight=2.0,
    ),
    EvaluationDimension(
        name="citation_quality",
        description="Citations are relevant, correctly attributed, and properly formatted",
        weight=1.5,
    ),
    EvaluationDimension(
        name="synthesis_coherence",
        description="Integrates multiple sources into unified understanding vs mere summarization",
        weight=2.0,
    ),
    EvaluationDimension(
        name="wiki_link_relevance",
        description="Wiki-style [[links]] point to appropriate, distinct concepts worth exploring",
        weight=1.0,
    ),
    EvaluationDimension(
        name="query_completeness",
        description="Thoroughly addresses the original query's intent",
        weight=1.5,
    ),
    EvaluationDimension(
        name="conciseness",
        description="Appropriately brief without sacrificing depth; no padding or redundancy",
        weight=1.0,
    ),
]


@dataclass
class DimensionScore:
    """Score for a single dimension."""

    dimension: str
    score: int  # 1-5
    reasoning: str
    suggestions: list[str] = field(default_factory=list)


@dataclass
class EvaluationResult:
    """Complete evaluation result."""

    # Identity
    note_path: str
    query: str
    evaluated_at: datetime = field(default_factory=datetime.now)

    # Scores
    dimension_scores: list[DimensionScore] = field(default_factory=list)
    overall_score: float = 0.0

    # Metadata
    judge_model: str = ""
    prompt_version: str = "v1"
    source_count: int = 0

    # Qualitative feedback
    strengths: list[str] = field(default_factory=list)
    weaknesses: list[str] = field(default_factory=list)
    improvement_suggestions: list[str] = field(default_factory=list)

    def compute_overall(self) -> float:
        """Compute weighted overall score."""
        if not self.dimension_scores:
            return 0.0

        dim_weights = {d.name: d.weight for d in EVAL_DIMENSIONS}

        weighted_sum = 0.0
        total_weight = 0.0
        for ds in self.dimension_scores:
            weight = dim_weights.get(ds.dimension, 1.0)
            weighted_sum += ds.score * weight
            total_weight += weight

        self.overall_score = weighted_sum / total_weight if total_weight > 0 else 0.0
        return self.overall_score

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON storage."""
        return {
            "note_path": self.note_path,
            "query": self.query,
            "evaluated_at": self.evaluated_at.isoformat(),
            "dimension_scores": [
                {
                    "dimension": ds.dimension,
                    "score": ds.score,
                    "reasoning": ds.reasoning,
                    "suggestions": ds.suggestions,
                }
                for ds in self.dimension_scores
            ],
            "overall_score": self.overall_score,
            "judge_model": self.judge_model,
            "prompt_version": self.prompt_version,
            "source_count": self.source_count,
            "strengths": self.strengths,
            "weaknesses": self.weaknesses,
            "improvement_suggestions": self.improvement_suggestions,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EvaluationResult":
        """Load from dictionary."""
        return cls(
            note_path=data["note_path"],
            query=data["query"],
            evaluated_at=datetime.fromisoformat(data["evaluated_at"]),
            dimension_scores=[
                DimensionScore(
                    dimension=ds["dimension"],
                    score=ds["score"],
                    reasoning=ds["reasoning"],
                    suggestions=ds.get("suggestions", []),
                )
                for ds in data["dimension_scores"]
            ],
            overall_score=data["overall_score"],
            judge_model=data.get("judge_model", ""),
            prompt_version=data.get("prompt_version", "v1"),
            source_count=data.get("source_count", 0),
            strengths=data.get("strengths", []),
            weaknesses=data.get("weaknesses", []),
            improvement_suggestions=data.get("improvement_suggestions", []),
        )

    def save(self, eval_dir: Path | str | None = None) -> Path:
        """Save evaluation result for APO training."""
        if eval_dir is None:
            kb_root = Path(os.getenv("GAIUS_KB_ROOT", "build/dev"))
            eval_dir = kb_root / "evaluations"
        eval_dir = Path(eval_dir)
        eval_dir.mkdir(parents=True, exist_ok=True)

        # Filename from note path
        timestamp = self.evaluated_at.strftime("%Y%m%d_%H%M%S")
        note_name = Path(self.note_path).stem if self.note_path else "unknown"
        filename = f"{timestamp}_{note_name}.json"

        path = eval_dir / filename
        path.write_text(json.dumps(self.to_dict(), indent=2))
        return path


# Judge prompt for frontier model
JUDGE_PROMPT = """You are an expert evaluator of knowledge synthesis quality. Your task is to evaluate a Zettelkasten note that was generated from search results.

## Evaluation Criteria

Score each dimension from 1-5:
- 1: Poor - Major issues, fails to meet basic standards
- 2: Below Average - Significant issues that detract from usefulness
- 3: Average - Meets basic expectations with some issues
- 4: Good - Well-executed with minor issues
- 5: Excellent - Exemplary quality, no significant issues

## Dimensions to Evaluate

{dimensions}

## Input

### Original Query
{query}

### Source Material Provided
{sources}

### Generated Zettelkasten Note
{note_content}

## Output Format

Respond with a JSON object (no markdown code fences):
{{
    "dimension_scores": [
        {{
            "dimension": "dimension_name",
            "score": 1-5,
            "reasoning": "Brief explanation for score",
            "suggestions": ["specific improvement suggestion"]
        }}
    ],
    "strengths": ["what the note does well"],
    "weaknesses": ["areas needing improvement"],
    "improvement_suggestions": ["actionable suggestions for the synthesis prompt"]
}}

Be critical but fair. Focus on actionable feedback that can improve the synthesis prompt."""


class SynthesisEvaluator:
    """Evaluates Zettelkasten synthesis quality using a frontier model judge."""

    # Supported backends
    BACKEND_ANTHROPIC = "anthropic"
    BACKEND_OPENAI = "openai"
    BACKEND_XAI = "xai"

    def __init__(
        self,
        judge_model: str | None = None,
        backend: str | None = None,
    ):
        """Initialize evaluator.

        Args:
            judge_model: Model to use for judging.
            backend: API backend to use: "anthropic", "openai", or "xai".
                    If None (default), auto-detect based on available API keys.
        """
        # Auto-detect which API to use
        if backend is None:
            anthropic_key = os.getenv("ANTHROPIC_API_KEY")
            openai_key = os.getenv("OPENAI_API_KEY")
            xai_key = os.getenv("XAI_API_KEY")

            # Priority: Anthropic > XAI > OpenAI
            if anthropic_key:
                backend = self.BACKEND_ANTHROPIC
            elif xai_key:
                backend = self.BACKEND_XAI
            elif openai_key:
                backend = self.BACKEND_OPENAI
            else:
                raise ValueError(
                    "No API key found. Set ANTHROPIC_API_KEY, XAI_API_KEY, or OPENAI_API_KEY"
                )

        self.backend = backend

        # Set default model per backend
        if judge_model:
            self.judge_model = judge_model
        elif backend == self.BACKEND_ANTHROPIC:
            self.judge_model = "claude-sonnet-4-20250514"
        elif backend == self.BACKEND_XAI:
            self.judge_model = "grok-3-mini-beta"
        else:
            self.judge_model = "gpt-4o"

        self._client = None

    def _get_client(self):
        """Get or create the judge client."""
        if self._client is not None:
            return self._client

        if self.backend == self.BACKEND_ANTHROPIC:
            try:
                import anthropic
                api_key = os.getenv("ANTHROPIC_API_KEY")
                if not api_key:
                    raise ValueError("ANTHROPIC_API_KEY required for evaluation")
                self._client = anthropic.Anthropic(api_key=api_key)
            except ImportError:
                raise ImportError(
                    "anthropic package required for evaluation. "
                    "Install with: pip install anthropic"
                )
        elif self.backend == self.BACKEND_XAI:
            try:
                from openai import OpenAI
                api_key = os.getenv("XAI_API_KEY")
                if not api_key:
                    raise ValueError("XAI_API_KEY required for evaluation")
                self._client = OpenAI(
                    api_key=api_key,
                    base_url="https://api.x.ai/v1",
                )
            except ImportError:
                raise ImportError(
                    "openai package required for XAI evaluation. "
                    "Install with: pip install openai"
                )
        else:  # OpenAI
            try:
                from openai import OpenAI
                api_key = os.getenv("OPENAI_API_KEY")
                if not api_key:
                    raise ValueError("OPENAI_API_KEY required for evaluation")
                self._client = OpenAI(api_key=api_key)
            except ImportError:
                raise ImportError(
                    "openai package required for evaluation. "
                    "Install with: pip install openai"
                )

        return self._client

    async def evaluate(
        self,
        note: ZettelkastenNote,
        sources: list[dict],
    ) -> EvaluationResult:
        """Evaluate a synthesized note.

        Args:
            note: The generated Zettelkasten note
            sources: The source materials used for synthesis

        Returns:
            EvaluationResult with scores and feedback
        """
        # Format dimensions for prompt
        dimensions_text = "\n".join(
            f"- **{d.name}** (weight {d.weight}): {d.description}"
            for d in EVAL_DIMENSIONS
        )

        # Format sources for prompt
        sources_text = []
        for i, s in enumerate(sources[:15], 1):  # Limit to 15 sources
            title = s.get("title", "Untitled")
            snippet = s.get("snippet", "")[:300]
            source_type = "Web" if s.get("url") else "KB"
            sources_text.append(f"{i}. [{source_type}] {title}\n   {snippet}")

        # Build prompt
        prompt = JUDGE_PROMPT.format(
            dimensions=dimensions_text,
            query=note.query,
            sources="\n".join(sources_text),
            note_content=note.to_markdown(),
        )

        # Call judge model
        response_text = await self._call_judge(prompt)

        # Parse response
        result = self._parse_response(response_text, note)
        result.judge_model = self.judge_model
        result.source_count = len(sources)
        result.compute_overall()

        return result

    async def _call_judge(self, prompt: str) -> str:
        """Call the judge model."""
        import asyncio

        client = self._get_client()

        if self.backend == self.BACKEND_ANTHROPIC:
            # Anthropic API (sync, run in executor)
            def call_anthropic():
                response = client.messages.create(
                    model=self.judge_model,
                    max_tokens=2048,
                    messages=[{"role": "user", "content": prompt}],
                )
                return response.content[0].text

            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, call_anthropic)
        else:
            # OpenAI-compatible API (OpenAI, XAI) - sync, run in executor
            def call_openai_compatible():
                response = client.chat.completions.create(
                    model=self.judge_model,
                    max_tokens=2048,
                    messages=[{"role": "user", "content": prompt}],
                )
                return response.choices[0].message.content

            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, call_openai_compatible)

    def _parse_response(
        self, response_text: str, note: ZettelkastenNote
    ) -> EvaluationResult:
        """Parse judge response into EvaluationResult."""
        # Try to extract JSON from response
        try:
            # Handle potential markdown code fences
            json_match = re.search(r'\{[\s\S]*\}', response_text)
            if json_match:
                data = json.loads(json_match.group())
            else:
                raise ValueError("No JSON found in response")
        except (json.JSONDecodeError, ValueError) as e:
            # Return error result
            return EvaluationResult(
                note_path=str(note.save()) if note else "",
                query=note.query if note else "",
                weaknesses=[f"Failed to parse judge response: {e}"],
                improvement_suggestions=["Improve response parsing"],
            )

        # Build result
        dimension_scores = []
        for ds in data.get("dimension_scores", []):
            dimension_scores.append(DimensionScore(
                dimension=ds.get("dimension", "unknown"),
                score=ds.get("score", 3),
                reasoning=ds.get("reasoning", ""),
                suggestions=ds.get("suggestions", []),
            ))

        return EvaluationResult(
            note_path="",  # Will be set by caller if needed
            query=note.query,
            dimension_scores=dimension_scores,
            strengths=data.get("strengths", []),
            weaknesses=data.get("weaknesses", []),
            improvement_suggestions=data.get("improvement_suggestions", []),
        )

    def evaluate_sync(
        self,
        note: ZettelkastenNote,
        sources: list[dict],
    ) -> EvaluationResult:
        """Synchronous wrapper for evaluate()."""
        import asyncio
        return asyncio.run(self.evaluate(note, sources))


# Module-level convenience functions
async def evaluate_synthesis(
    note: ZettelkastenNote,
    sources: list[dict],
    save: bool = True,
) -> EvaluationResult:
    """Convenience function to evaluate and optionally save results."""
    evaluator = SynthesisEvaluator()
    result = await evaluator.evaluate(note, sources)

    if save:
        result.save()

    return result


def load_evaluations(
    eval_dir: Path | str | None = None,
    min_date: datetime | None = None,
) -> list[EvaluationResult]:
    """Load evaluation results for APO analysis."""
    if eval_dir is None:
        kb_root = Path(os.getenv("GAIUS_KB_ROOT", "build/dev"))
        eval_dir = kb_root / "evaluations"
    eval_dir = Path(eval_dir)

    if not eval_dir.exists():
        return []

    results = []
    for path in sorted(eval_dir.glob("*.json")):
        try:
            data = json.loads(path.read_text())
            result = EvaluationResult.from_dict(data)

            if min_date and result.evaluated_at < min_date:
                continue

            results.append(result)
        except Exception:
            continue

    return results


def compute_aggregate_scores(
    results: list[EvaluationResult],
) -> dict[str, float]:
    """Compute aggregate scores across multiple evaluations.

    Returns dict with dimension means and overall mean.
    Useful for tracking improvement over time.
    """
    if not results:
        return {"overall": 0.0}

    # Collect scores by dimension
    dim_scores: dict[str, list[int]] = {}
    overall_scores = []

    for r in results:
        overall_scores.append(r.overall_score)
        for ds in r.dimension_scores:
            if ds.dimension not in dim_scores:
                dim_scores[ds.dimension] = []
            dim_scores[ds.dimension].append(ds.score)

    # Compute means
    aggregates = {
        "overall": sum(overall_scores) / len(overall_scores),
    }
    for dim, scores in dim_scores.items():
        aggregates[dim] = sum(scores) / len(scores)

    return aggregates
