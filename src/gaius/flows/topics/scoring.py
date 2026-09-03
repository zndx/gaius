"""LLM-based paper relevance scoring with rubric artifacts.

Supports local and remote model scoring with versioned rubrics
for consistent and reproducible paper selection.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml
from gaius.core.budgets import REASONING_MAX_TOKENS

logger = logging.getLogger(__name__)


@dataclass
class ScoringCriterion:
    """A single scoring criterion within a rubric."""

    name: str
    weight: float
    description: str
    examples: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "weight": self.weight,
            "description": self.description,
            "examples": self.examples,
        }


@dataclass
class ScoringRubric:
    """Versioned scoring rubric for paper selection."""

    name: str
    version: str
    criteria: list[ScoringCriterion]
    model_preference: str = "ensemble"  # local, remote, ensemble
    local_model: str | None = None
    remote_model: str | None = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @property
    def total_weight(self) -> float:
        return sum(c.weight for c in self.criteria)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "version": self.version,
            "model_preference": self.model_preference,
            "local_model": self.local_model,
            "remote_model": self.remote_model,
            "criteria": [c.to_dict() for c in self.criteria],
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ScoringRubric":
        return cls(
            name=data["name"],
            version=data["version"],
            model_preference=data.get("model_preference", "ensemble"),
            local_model=data.get("local_model"),
            remote_model=data.get("remote_model"),
            criteria=[
                ScoringCriterion(
                    name=c["name"],
                    weight=c["weight"],
                    description=c["description"],
                    examples=c.get("examples", []),
                )
                for c in data["criteria"]
            ],
            created_at=data.get("created_at", datetime.now(timezone.utc).isoformat()),
        )


@dataclass
class PaperScore:
    """Scored paper with detailed criteria breakdown."""

    arxiv_id: str
    overall_score: float  # 0-1 weighted average
    criteria_scores: dict[str, float]  # criterion name -> score (0-1)
    rubric_name: str
    rubric_version: str
    model_used: str
    reasoning: str | None = None
    confidence: float | None = None
    scored_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict:
        return {
            "arxiv_id": self.arxiv_id,
            "overall_score": self.overall_score,
            "criteria_scores": self.criteria_scores,
            "rubric_name": self.rubric_name,
            "rubric_version": self.rubric_version,
            "model_used": self.model_used,
            "reasoning": self.reasoning,
            "confidence": self.confidence,
            "scored_at": self.scored_at,
        }


def load_rubric(
    name: str = "default",
    config_dir: str | Path | None = None,
) -> ScoringRubric:
    """Load scoring rubric from YAML config.

    Args:
        name: Rubric name (default: "default")
        config_dir: Config directory path (default: config/scoring_rubrics)

    Returns:
        ScoringRubric instance
    """
    if config_dir is None:
        # Find config relative to project root
        project_root = Path(__file__).parent.parent.parent.parent.parent
        resolved_dir = project_root / "config" / "scoring_rubrics"
    else:
        resolved_dir = Path(config_dir)

    config_path = resolved_dir / f"{name}.yaml"

    if not config_path.exists():
        logger.warning(f"Rubric {name} not found, using defaults")
        return get_default_rubric()

    with open(config_path) as f:
        data = yaml.safe_load(f)

    data["name"] = name
    return ScoringRubric.from_dict(data)


def get_default_rubric() -> ScoringRubric:
    """Get built-in default scoring rubric."""
    return ScoringRubric(
        name="default",
        version="1.0.0",
        model_preference="ensemble",
        criteria=[
            ScoringCriterion(
                name="relevance_to_kb",
                weight=0.30,
                description="How relevant is this paper to existing KB topics and domains?",
                examples=["Topics align with existing research areas", "Extends current KB knowledge"],
            ),
            ScoringCriterion(
                name="novelty",
                weight=0.25,
                description="Does this paper introduce new concepts, methods, or insights?",
                examples=["Novel approach to known problem", "First-of-kind methodology"],
            ),
            ScoringCriterion(
                name="technical_depth",
                weight=0.25,
                description="Is this paper technically substantial with rigorous methodology?",
                examples=["Formal proofs or derivations", "Comprehensive experiments"],
            ),
            ScoringCriterion(
                name="practical_applicability",
                weight=0.20,
                description="Can insights from this paper be applied to Gaius development?",
                examples=["Applicable algorithms", "Architecture patterns"],
            ),
        ],
    )


def _build_scoring_prompt(
    abstract: str,
    rubric: ScoringRubric,
    arxiv_id: str = "",
) -> str:
    """Build structured prompt for LLM scoring."""
    criteria_text = ""
    for c in rubric.criteria:
        examples_str = ", ".join(c.examples[:2]) if c.examples else "N/A"
        criteria_text += f"""
- **{c.name}** (weight: {c.weight:.0%})
  - {c.description}
  - Examples: {examples_str}
"""

    prompt = f"""You are evaluating an arXiv paper for inclusion in a research knowledge base.

## Paper Information
{f'arXiv ID: {arxiv_id}' if arxiv_id else ''}

### Abstract
{abstract}

## Evaluation Criteria
{criteria_text}

## Instructions
1. Score each criterion from 0.0 (not applicable) to 1.0 (excellent match)
2. Consider the paper's potential contribution to a technical knowledge base
3. Provide brief reasoning for each score

## Required Output Format
Return a valid JSON object with this exact structure:
```json
{{
  "scores": {{
    "relevance_to_kb": 0.0,
    "novelty": 0.0,
    "technical_depth": 0.0,
    "practical_applicability": 0.0
  }},
  "reasoning": "Brief explanation of the scores",
  "confidence": 0.0
}}
```

Return ONLY the JSON object, no additional text."""

    return prompt


def _parse_scoring_response(response: str) -> dict:
    """Parse LLM response to extract scores."""
    # Try to extract JSON from response
    response = response.strip()

    # Handle markdown code blocks
    if "```json" in response:
        start = response.find("```json") + 7
        end = response.find("```", start)
        response = response[start:end].strip()
    elif "```" in response:
        start = response.find("```") + 3
        end = response.find("```", start)
        response = response[start:end].strip()

    try:
        data = json.loads(response)
        return {
            "scores": data.get("scores", {}),
            "reasoning": data.get("reasoning", ""),
            "confidence": data.get("confidence", 0.5),
        }
    except json.JSONDecodeError as e:
        logger.warning(f"Failed to parse scoring response: {e}")
        return {
            "scores": {},
            "reasoning": "Failed to parse response",
            "confidence": 0.0,
        }


async def score_paper(
    abstract: str,
    rubric: ScoringRubric,
    arxiv_id: str = "",
    use_local: bool = True,
    use_remote: bool = False,
) -> PaperScore:
    """Score paper relevance using LLM with rubric.

    Args:
        abstract: Paper abstract text
        rubric: Scoring rubric to apply
        arxiv_id: arXiv paper ID (for tracking)
        use_local: Use local model (vLLM)
        use_remote: Use remote model (frontier API)

    Returns:
        PaperScore with criteria scores and reasoning
    """
    from gaius.client.engine_client import get_engine_client

    prompt = _build_scoring_prompt(abstract, rubric, arxiv_id)

    engine = await get_engine_client()
    model_used = "unknown"

    if rubric.model_preference == "ensemble" and use_local and use_remote:
        # Score twice and average (both via Engine/Complete)
        local_result = await engine.complete_simple(prompt, max_tokens=REASONING_MAX_TOKENS)
        remote_result = await engine.complete_simple(prompt, max_tokens=REASONING_MAX_TOKENS, temperature=0.5)

        # Extract content from CompletionResult objects
        local_content = local_result.content if hasattr(local_result, 'content') else str(local_result)
        remote_content = remote_result.content if hasattr(remote_result, 'content') else str(remote_result)

        local_parsed = _parse_scoring_response(local_content)
        remote_parsed = _parse_scoring_response(remote_content)

        # Merge scores (average)
        scores = {}
        for criterion in rubric.criteria:
            local_score = local_parsed["scores"].get(criterion.name, 0.5)
            remote_score = remote_parsed["scores"].get(criterion.name, 0.5)
            scores[criterion.name] = (local_score + remote_score) / 2

        reasoning = f"Local: {local_parsed['reasoning']}\nRemote: {remote_parsed['reasoning']}"
        confidence = (local_parsed["confidence"] + remote_parsed["confidence"]) / 2
        model_used = "ensemble"

    elif use_remote:
        result = await engine.complete_simple(prompt, max_tokens=REASONING_MAX_TOKENS, temperature=0.5)
        # Extract content from CompletionResult object
        content = result.content if hasattr(result, 'content') else str(result)
        parsed = _parse_scoring_response(content)
        scores = parsed["scores"]
        reasoning = parsed["reasoning"]
        confidence = parsed["confidence"]
        model_used = rubric.remote_model or "frontier"

    else:
        # Default to local
        result = await engine.complete_simple(prompt, max_tokens=REASONING_MAX_TOKENS)
        # Extract content from CompletionResult object
        content = result.content if hasattr(result, 'content') else str(result)
        parsed = _parse_scoring_response(content)
        scores = parsed["scores"]
        reasoning = parsed["reasoning"]
        confidence = parsed["confidence"]
        model_used = rubric.local_model or "local"

    # Calculate weighted overall score
    overall = 0.0
    total_weight = 0.0
    for criterion in rubric.criteria:
        score = scores.get(criterion.name, 0.0)
        overall += score * criterion.weight
        total_weight += criterion.weight

    if total_weight > 0:
        overall /= total_weight

    return PaperScore(
        arxiv_id=arxiv_id,
        overall_score=overall,
        criteria_scores=scores,
        rubric_name=rubric.name,
        rubric_version=rubric.version,
        model_used=model_used,
        reasoning=reasoning,
        confidence=confidence,
    )


async def score_batch(
    papers: list[dict],
    rubric: ScoringRubric,
    use_remote_calibration: bool = True,
    calibration_sample_size: int = 3,
) -> list[PaperScore]:
    """Score a batch of papers with optional remote calibration.

    Args:
        papers: List of dicts with 'arxiv_id' and 'abstract'
        rubric: Scoring rubric to apply
        use_remote_calibration: Use remote model to calibrate local scores
        calibration_sample_size: Number of papers for calibration

    Returns:
        List of PaperScore objects
    """
    import asyncio
    import random

    if not papers:
        return []

    scores = []

    # If using calibration, score a sample with both models
    if use_remote_calibration and len(papers) >= calibration_sample_size:
        calibration_papers = random.sample(papers, calibration_sample_size)
        calibration_ids = {p["arxiv_id"] for p in calibration_papers}

        # Score calibration papers with ensemble
        for paper in calibration_papers:
            score = await score_paper(
                paper["abstract"],
                rubric,
                arxiv_id=paper["arxiv_id"],
                use_local=True,
                use_remote=True,
            )
            scores.append(score)

        # Score remaining papers with local only
        for paper in papers:
            if paper["arxiv_id"] not in calibration_ids:
                score = await score_paper(
                    paper["abstract"],
                    rubric,
                    arxiv_id=paper["arxiv_id"],
                    use_local=True,
                    use_remote=False,
                )
                scores.append(score)
    else:
        # Score all with local
        for paper in papers:
            score = await score_paper(
                paper["abstract"],
                rubric,
                arxiv_id=paper["arxiv_id"],
                use_local=True,
                use_remote=False,
            )
            scores.append(score)

    return scores


def filter_by_score(
    scores: list[PaperScore],
    min_score: float = 0.5,
    min_confidence: float = 0.3,
) -> list[PaperScore]:
    """Filter papers by minimum score threshold.

    Args:
        scores: List of PaperScore objects
        min_score: Minimum overall score (0-1)
        min_confidence: Minimum confidence level

    Returns:
        Filtered list of papers meeting thresholds
    """
    return [
        s for s in scores
        if s.overall_score >= min_score
        and (s.confidence or 0) >= min_confidence
    ]


def rank_papers(
    scores: list[PaperScore],
    top_n: int | None = None,
) -> list[PaperScore]:
    """Rank papers by overall score.

    Args:
        scores: List of PaperScore objects
        top_n: Return only top N papers (None for all)

    Returns:
        Sorted list, highest score first
    """
    sorted_scores = sorted(scores, key=lambda s: s.overall_score, reverse=True)
    if top_n:
        return sorted_scores[:top_n]
    return sorted_scores
