"""Reward computation for research quality scoring.

Three orthogonal dimensions for evaluating research quality:
- Coherence (40%): Logical flow, consistency, argumentation
- Coverage (35%): Query aspects addressed, source utilization
- Novelty (25%): Distance from prior research, new insights

Guru Meditation Codes:
- #RF.00000004.EVALFAIL: Reward computation failed
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

import numpy as np

logger = logging.getLogger(__name__)

# Reward weights
WEIGHT_COHERENCE = 0.40
WEIGHT_COVERAGE = 0.35
WEIGHT_NOVELTY = 0.25


@dataclass
class RewardComponents:
    """Reward signal components for research quality.

    Total reward = 0.40*coherence + 0.35*coverage + 0.25*novelty
    """

    coherence: float = 0.0  # Logical flow, consistency
    coverage: float = 0.0  # Query aspects addressed
    novelty: float = 0.0  # Distance from prior research

    @property
    def total(self) -> float:
        """Compute weighted total reward."""
        return (
            WEIGHT_COHERENCE * self.coherence
            + WEIGHT_COVERAGE * self.coverage
            + WEIGHT_NOVELTY * self.novelty
        )

    def to_dict(self) -> dict[str, float]:
        """Convert to dictionary for frontmatter."""
        return {
            "coherence": round(self.coherence, 3),
            "coverage": round(self.coverage, 3),
            "novelty": round(self.novelty, 3),
        }

    def __str__(self) -> str:
        return (
            f"RewardComponents(coherence={self.coherence:.2f}, "
            f"coverage={self.coverage:.2f}, novelty={self.novelty:.2f}, "
            f"total={self.total:.2f})"
        )


async def score_coherence(synthesis: str) -> float:
    """Score logical coherence of synthesis text.

    Heuristics:
    - Section structure (headers, paragraphs)
    - Transition words (therefore, however, thus)
    - Consistent terminology
    - Citation integration

    Args:
        synthesis: The synthesis text to score.

    Returns:
        Coherence score (0-1).
    """
    if not synthesis:
        return 0.0

    score = 0.0

    # Section structure (0-0.3)
    has_headers = bool(re.search(r"^#+\s", synthesis, re.MULTILINE))
    paragraph_count = len(re.findall(r"\n\n", synthesis))
    structure_score = 0.15 if has_headers else 0.0
    structure_score += min(0.15, paragraph_count * 0.03)
    score += structure_score

    # Transition words (0-0.3)
    transition_words = [
        "therefore",
        "however",
        "thus",
        "consequently",
        "furthermore",
        "moreover",
        "additionally",
        "in contrast",
        "similarly",
        "as a result",
        "for example",
        "specifically",
        "in particular",
    ]
    transition_count = sum(
        1 for word in transition_words if word.lower() in synthesis.lower()
    )
    transition_score = min(0.3, transition_count * 0.05)
    score += transition_score

    # Citation integration (0-0.2)
    kb_citations = len(re.findall(r"\[\[.*?\]\]", synthesis))
    web_citations = len(re.findall(r"\[.*?\]\(http", synthesis))
    citation_score = min(0.2, (kb_citations + web_citations) * 0.04)
    score += citation_score

    # Length and depth (0-0.2)
    word_count = len(synthesis.split())
    length_score = min(0.2, word_count / 2000)  # Max at 2000 words
    score += length_score

    return min(1.0, score)


async def score_coverage(
    query: str,
    synthesis: str,
    sources: list[dict[str, str]],
) -> float:
    """Score how well the synthesis covers the query.

    Heuristics:
    - Query term presence
    - Source utilization ratio
    - Multiple perspectives
    - Key findings section

    Args:
        query: Original search query.
        synthesis: The synthesis text.
        sources: List of source dicts with 'title' and 'url'.

    Returns:
        Coverage score (0-1).
    """
    if not synthesis:
        return 0.0

    score = 0.0

    # Query term coverage (0-0.4)
    query_terms = set(
        word.lower()
        for word in re.findall(r"\w+", query)
        if len(word) > 2
    )
    synthesis_lower = synthesis.lower()
    terms_found = sum(1 for term in query_terms if term in synthesis_lower)
    term_coverage = terms_found / max(1, len(query_terms))
    score += 0.4 * term_coverage

    # Source utilization (0-0.3)
    if sources:
        # Count sources actually cited
        citations_found = 0
        for source in sources:
            title = source.get("title", "")
            url = source.get("url", "")
            if title and title[:20].lower() in synthesis_lower:
                citations_found += 1
            elif url and url in synthesis:
                citations_found += 1
        utilization = citations_found / len(sources)
        score += 0.3 * utilization
    else:
        # No sources to cite, give partial credit
        score += 0.15

    # Key findings section (0-0.15)
    has_findings = bool(
        re.search(r"(key findings|main points|summary|conclusions)", synthesis, re.I)
    )
    score += 0.15 if has_findings else 0.0

    # Multiple perspectives (0-0.15)
    perspective_markers = [
        "on one hand",
        "alternatively",
        "from another perspective",
        "critics argue",
        "proponents suggest",
        "risk",
        "opportunity",
        "trade-off",
    ]
    perspectives_found = sum(
        1 for marker in perspective_markers if marker.lower() in synthesis_lower
    )
    perspective_score = min(0.15, perspectives_found * 0.03)
    score += perspective_score

    return min(1.0, score)


def compute_novelty(
    synthesis: str,
    prior_syntheses: list[str],
) -> float:
    """Compute novelty score based on distance from prior research.

    Uses simple text-based similarity (Jaccard) for efficiency.
    For production, would use embedding cosine distance.

    Args:
        synthesis: Current synthesis text.
        prior_syntheses: List of prior synthesis texts.

    Returns:
        Novelty score (0-1). Higher = more novel.
    """
    if not synthesis or not prior_syntheses:
        # No prior research = maximum novelty
        return 1.0

    # Tokenize current synthesis
    current_tokens = set(
        word.lower()
        for word in re.findall(r"\w+", synthesis)
        if len(word) > 3
    )

    if not current_tokens:
        return 0.5

    # Compute average Jaccard distance from prior syntheses
    distances = []
    for prior in prior_syntheses:
        prior_tokens = set(
            word.lower()
            for word in re.findall(r"\w+", prior)
            if len(word) > 3
        )
        if not prior_tokens:
            continue

        intersection = len(current_tokens & prior_tokens)
        union = len(current_tokens | prior_tokens)
        jaccard_similarity = intersection / union if union > 0 else 0
        jaccard_distance = 1 - jaccard_similarity
        distances.append(jaccard_distance)

    if not distances:
        return 1.0

    # Average distance = novelty
    return float(np.mean(distances))


async def compute_reward(
    synthesis: str,
    query: str,
    sources: list[dict[str, str]],
    prior_syntheses: list[str] | None = None,
) -> RewardComponents:
    """Compute full reward signal for a research pass.

    Args:
        synthesis: The synthesis text to evaluate.
        query: Original search query.
        sources: List of source dicts with 'title' and 'url'.
        prior_syntheses: Optional list of prior synthesis texts for novelty.

    Returns:
        RewardComponents with individual and total scores.
    """
    try:
        coherence = await score_coherence(synthesis)
        coverage = await score_coverage(query, synthesis, sources)
        novelty = compute_novelty(synthesis, prior_syntheses or [])

        reward = RewardComponents(
            coherence=coherence,
            coverage=coverage,
            novelty=novelty,
        )

        logger.info(f"Computed reward: {reward}")
        return reward

    except Exception as e:
        logger.error(f"Reward computation failed: {e}")
        from gaius.flows.research import RewardError
        raise RewardError(
            f"Reward computation failed: {e}",
            guru_code="#RF.00000004.EVALFAIL",
            hint="/health fix endpoints",
        ) from e


async def score_with_llm(
    synthesis: str,
    query: str,
    evaluator: str = "local",
) -> RewardComponents:
    """Score synthesis using LLM evaluation (optional enhancement).

    This is a more sophisticated scoring method that uses an LLM
    to evaluate the quality of the synthesis. More expensive but
    more accurate than heuristics.

    Args:
        synthesis: The synthesis text to evaluate.
        query: Original search query.
        evaluator: Which evaluator to use ('local', 'grok', 'cerebras').

    Returns:
        RewardComponents from LLM evaluation.
    """
    # Import evaluator based on choice
    if evaluator == "grok":
        from gaius.engine.backends.external.xai_backend import XAIBackend

        backend = XAIBackend()
    elif evaluator == "cerebras":
        from gaius.engine.backends.external.cerebras_backend import CerebrasBackend

        backend = CerebrasBackend()
    else:
        # Use local instruct model
        from gaius.engine.backends.instruct_backend import InstructBackend

        backend = InstructBackend()

    prompt = f"""Evaluate this research synthesis on a scale of 0-1 for each dimension:

**Query**: {query}

**Synthesis**:
{synthesis[:3000]}...

Rate each dimension:
1. **Coherence** (0-1): Logical flow, consistent argumentation, clear structure
2. **Coverage** (0-1): How well it addresses the query, source utilization
3. **Novelty** (0-1): Fresh insights beyond obvious information

Respond in JSON format:
{{"coherence": 0.X, "coverage": 0.X, "novelty": 0.X}}
"""

    try:
        response = await backend.complete(prompt, max_tokens=100)
        # Parse JSON from response
        import json

        # Find JSON in response
        json_match = re.search(r"\{[^}]+\}", response)
        if json_match:
            scores = json.loads(json_match.group())
            return RewardComponents(
                coherence=float(scores.get("coherence", 0.5)),
                coverage=float(scores.get("coverage", 0.5)),
                novelty=float(scores.get("novelty", 0.5)),
            )
    except Exception as e:
        logger.error(f"LLM scoring failed: {e}")
        from gaius.flows.research import RewardError
        raise RewardError(
            f"LLM scoring failed: {e}",
            guru_code="#RF.00000012.LLMSCOREFAIL",
            hint="/health fix endpoints",
        ) from e
