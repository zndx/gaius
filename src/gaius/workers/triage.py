"""Content triage module for quality scoring.

Implements two-stage content triage:
1. Heuristic scoring - Fast, no LLM required
2. LLM quality assessment - via the Engine (gRPC Complete)

Triage scores are stored in:
- content_items.heuristic_score (0-100)
- content_items.llm_quality_score (0-100)
- triage_assessments table for lineage tracking

Pipeline Flow:
  fetch → heuristic_triage → llm_triage → kb_creation

Scores are combined for final quality determination:
  combined_score = (heuristic_score * 0.4) + (llm_quality_score * 0.6)
"""

import asyncio
import hashlib
import json
import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

from gaius.workers.config import WorkerConfig
from gaius.workers.db import Database
from gaius.workers.models import ContentItem

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class TriageConfig:
    """Configuration for triage operations."""

    # Heuristic scoring weights (must sum to 1.0)
    weight_content_length: float = 0.3
    weight_title_quality: float = 0.2
    weight_metadata_complete: float = 0.3
    weight_source_reputation: float = 0.2

    # Score thresholds
    heuristic_threshold: int = 30  # Minimum to proceed to LLM triage
    combined_threshold: int = 50   # Minimum for KB inclusion

    # Processing limits
    batch_size: int = 50

    @classmethod
    def from_env(cls) -> "TriageConfig":
        """Create config from environment variables."""
        return cls(
            batch_size=int(os.getenv("TRIAGE_BATCH_SIZE", "50")),
        )


# ─────────────────────────────────────────────────────────────────────────────
# Heuristic Scoring
# ─────────────────────────────────────────────────────────────────────────────


class HeuristicScorer:
    """Computes heuristic quality scores without LLM."""

    # Source reputation scores (0-100)
    SOURCE_REPUTATION = {
        "arxiv": 90,
        "pubmed": 90,
        "biorxiv": 85,
        "medrxiv": 85,
        "philpapers": 80,
        "philevents": 75,
        "rss": 60,
        "brave": 50,
        "web": 40,
        "unknown": 30,
    }

    def __init__(self, config: TriageConfig):
        self.config = config

    def score(self, item: ContentItem) -> dict:
        """Compute heuristic score for a content item.

        Returns:
            Dict with score breakdown and total
        """
        scores = {
            "content_length": self._score_content_length(item),
            "title_quality": self._score_title_quality(item),
            "metadata_complete": self._score_metadata_complete(item),
            "source_reputation": self._score_source_reputation(item),
        }

        # Weighted total
        total = (
            scores["content_length"] * self.config.weight_content_length +
            scores["title_quality"] * self.config.weight_title_quality +
            scores["metadata_complete"] * self.config.weight_metadata_complete +
            scores["source_reputation"] * self.config.weight_source_reputation
        )

        return {
            "scores": scores,
            "total": int(total),
            "excluded": total < self.config.heuristic_threshold,
        }

    def _score_content_length(self, item: ContentItem) -> int:
        """Score based on content length.

        < 100 chars: 0
        100-500 chars: 20
        500-2000 chars: 50
        2000-10000 chars: 80
        > 10000 chars: 100
        """
        content = item.content or ""
        length = len(content)

        if length < 100:
            return 0
        elif length < 500:
            return 20
        elif length < 2000:
            return 50
        elif length < 10000:
            return 80
        else:
            return 100

    def _score_title_quality(self, item: ContentItem) -> int:
        """Score based on title quality.

        Checks for:
        - Minimum length
        - Not all caps
        - Contains words (not just punctuation)
        - Not generic
        """
        title = item.title or ""
        score = 0

        # Minimum length
        if len(title) > 10:
            score += 25

        # Not all caps
        if not title.isupper():
            score += 25

        # Contains multiple words
        words = title.split()
        if len(words) >= 3:
            score += 25

        # Not generic (contains specific terms)
        generic_terms = ["untitled", "no title", "test", "sample", "example"]
        if not any(term in title.lower() for term in generic_terms):
            score += 25

        return score

    def _score_metadata_complete(self, item: ContentItem) -> int:
        """Score based on metadata completeness.

        Points for:
        - URL present (20)
        - Authors present (30)
        - Published date (20)
        - Summary present (30)
        """
        score = 0

        if item.url:
            score += 20

        if item.authors and len(item.authors) > 0:
            score += 30

        if item.published_at:
            score += 20

        if item.summary and len(item.summary) > 50:
            score += 30

        return score

    def _score_source_reputation(self, item: ContentItem) -> int:
        """Score based on source type reputation."""
        source_type = item.metadata.get("source_type", "unknown")
        return self.SOURCE_REPUTATION.get(source_type.lower(), 30)


# ─────────────────────────────────────────────────────────────────────────────
# LLM Quality Assessment
# ─────────────────────────────────────────────────────────────────────────────


class LLMTriageAssessor:
    """Assesses content quality using LLM."""

    ASSESSMENT_PROMPT = """Assess the quality of this content for inclusion in a knowledge base.

Title: {title}

Summary: {summary}

Content (first 2000 chars): {content_preview}

Rate the following on a scale of 0-100:
1. Relevance: Is this content informative and useful?
2. Quality: Is the writing clear and well-structured?
3. Completeness: Does it provide sufficient information?
4. Originality: Does it offer unique insights?

Respond with JSON only:
{{"relevance": <0-100>, "quality": <0-100>, "completeness": <0-100>, "originality": <0-100>, "overall": <0-100>, "reasoning": "<brief explanation>"}}"""

    def __init__(self, config: TriageConfig):
        self.config = config

    async def close(self):
        """Kept for API compatibility (no owned transport since the gRPC rewire)."""

    async def assess(self, item: ContentItem) -> dict:
        """Assess content quality using the Engine (gRPC Complete).

        Engine-First, no bypass: inference is consumed ONLY through the engine's
        gRPC — never optillm's HTTP :8000 or a vLLM directly (this class used to
        POST to optillm and was shared by the gaius-worker AND the engine's
        cognition_service; both now route through Engine/Complete).

        FAIL-FAST: raises on engine failure or an unparseable assessment — the
        caller records the error and leaves the item honestly unscored (retried
        next pass). Never invents a neutral score.

        Returns:
            Dict with scores and assessment
        """
        from gaius.client.engine_client import get_engine_client

        prompt = self.ASSESSMENT_PROMPT.format(
            title=item.title or "No title",
            summary=item.summary or "No summary",
            content_preview=(item.content or "")[:2000],
        )

        client = await get_engine_client()
        result = await client.complete_simple(
            prompt=prompt,
            temperature=0.1,
            max_tokens=500,
        )
        content = result.content or ""
        scores = self._parse_assessment(content)
        return {
            "scores": scores,
            "total": scores["overall"],
            "reasoning": scores.get("reasoning", ""),
        }

    def _parse_assessment(self, content: str) -> dict:
        """Parse the LLM response into scores. FAIL-FAST on unparseable output."""
        try:
            json_match = re.search(r'\{[^{}]*\}', content, re.DOTALL)
            if json_match:
                scores = json.loads(json_match.group())
                if "overall" in scores:
                    return scores
        except json.JSONDecodeError:
            pass
        raise RuntimeError(
            "LLM triage assessment unparseable (no JSON with 'overall').\n"
            "  Guru Meditation: #TR.00000001.BADASSESS\n"
            f"  Response head: {content[:200]!r}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Duplicate Detection
# ─────────────────────────────────────────────────────────────────────────────


class DuplicateDetector:
    """Detects duplicate content using content hashes."""

    def __init__(self, db: Database):
        self.db = db
        self._seen_hashes: set[str] = set()

    async def load_existing_hashes(self, scenario_id: Optional[str] = None):
        """Load existing content hashes from database."""
        query = "SELECT content_hash FROM content_items WHERE content_hash IS NOT NULL"
        if scenario_id:
            query += f" AND id LIKE '%{scenario_id}%'"

        rows = await self.db.pool.fetch(query)
        self._seen_hashes = {row["content_hash"] for row in rows}

    def compute_hash(self, item: ContentItem) -> str:
        """Compute content hash for deduplication."""
        content = f"{item.title}|{item.content or ''}|{item.url or ''}"
        return hashlib.sha256(content.encode()).hexdigest()[:32]

    def is_duplicate(self, item: ContentItem) -> bool:
        """Check if content is a duplicate."""
        hash_value = self.compute_hash(item)
        if hash_value in self._seen_hashes:
            return True
        self._seen_hashes.add(hash_value)
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Triage Pipeline
# ─────────────────────────────────────────────────────────────────────────────


class TriagePipeline:
    """Orchestrates the two-stage triage process."""

    def __init__(
        self,
        config: TriageConfig,
        db: Database,
    ):
        self.config = config
        self.db = db
        self.heuristic_scorer = HeuristicScorer(config)
        self.llm_assessor = LLMTriageAssessor(config)
        self.duplicate_detector = DuplicateDetector(db)

    async def close(self):
        """Clean up resources."""
        await self.llm_assessor.close()

    async def run_heuristic_triage(
        self,
        scenario_id: Optional[str] = None,
        limit: int = 50,
    ) -> list[dict]:
        """Run heuristic triage on unscored items.

        Args:
            scenario_id: Optional filter for test isolation
            limit: Maximum items to process

        Returns:
            List of triage results
        """
        # Get unscored items
        items = await self._get_items_for_heuristic_triage(scenario_id, limit)
        if not items:
            return []

        results = []
        for item in items:
            # Score item
            result = self.heuristic_scorer.score(item)
            result["item_id"] = item.id
            result["title"] = item.title

            # Save score
            await self._save_heuristic_score(item.id, result["total"])

            # Create lineage record
            await self._create_assessment_record(
                item.id,
                "heuristic",
                result["total"],
                result["scores"],
            )

            results.append(result)

        logger.info(f"Heuristic triage completed: {len(results)} items scored")
        return results

    async def run_llm_triage(
        self,
        scenario_id: Optional[str] = None,
        limit: int = 20,
    ) -> list[dict]:
        """Run LLM triage on heuristic-passed items.

        Args:
            scenario_id: Optional filter for test isolation
            limit: Maximum items to process

        Returns:
            List of triage results
        """
        # Load duplicate hashes
        await self.duplicate_detector.load_existing_hashes(scenario_id)

        # Get items that passed heuristic triage
        items = await self._get_items_for_llm_triage(scenario_id, limit)
        if not items:
            return []

        results = []
        for item in items:
            # Check for duplicates
            if self.duplicate_detector.is_duplicate(item):
                await self._mark_summary_excluded(item.id, "duplicate")
                results.append({
                    "item_id": item.id,
                    "title": item.title,
                    "excluded": True,
                    "reason": "duplicate",
                })
                continue

            # LLM assessment. FAIL-FAST per item: on error the item stays
            # honestly UNSCORED (llm_quality_score NULL → retried next pass);
            # we never write an invented neutral score.
            try:
                result = await self.llm_assessor.assess(item)
            except Exception as e:  # noqa: BLE001 — surfaced, counted, not faked
                logger.error(f"LLM triage failed for {item.id}: {e}")
                results.append({
                    "item_id": item.id,
                    "title": item.title,
                    "error": str(e),
                })
                continue
            result["item_id"] = item.id
            result["title"] = item.title

            # Save score
            await self._save_llm_score(item.id, result["total"])

            # Calculate combined score
            heuristic = await self._get_heuristic_score(item.id)
            combined = int(
                heuristic * 0.4 +
                result["total"] * 0.6
            )
            result["heuristic_score"] = heuristic
            result["llm_quality_score"] = result["total"]
            result["combined_score"] = combined

            # Create lineage record
            await self._create_assessment_record(
                item.id,
                "llm",
                result["total"],
                result.get("scores", {}),
            )

            # Mark excluded if below threshold
            if combined < self.config.combined_threshold:
                await self._mark_summary_excluded(item.id, "low_quality")
                result["excluded"] = True
            else:
                result["excluded"] = False

            results.append(result)

        logger.info(f"LLM triage completed: {len(results)} items assessed")
        return results

    async def _get_items_for_heuristic_triage(
        self,
        scenario_id: Optional[str],
        limit: int,
    ) -> list[ContentItem]:
        """Get items that need heuristic scoring."""
        query = """
            SELECT * FROM content_items
            WHERE heuristic_score IS NULL
        """
        if scenario_id:
            query += f" AND id LIKE '%{scenario_id}%'"
        query += f" ORDER BY fetched_at DESC LIMIT {limit}"

        rows = await self.db.pool.fetch(query)
        return [ContentItem.from_row(dict(row)) for row in rows]

    async def _get_items_for_llm_triage(
        self,
        scenario_id: Optional[str],
        limit: int,
    ) -> list[ContentItem]:
        """Get items that passed heuristic and need LLM scoring."""
        query = f"""
            SELECT * FROM content_items
            WHERE heuristic_score >= {self.config.heuristic_threshold}
              AND llm_quality_score IS NULL
              AND summary_excluded IS NOT TRUE
        """
        if scenario_id:
            query += f" AND id LIKE '%{scenario_id}%'"
        query += f" ORDER BY heuristic_score DESC LIMIT {limit}"

        rows = await self.db.pool.fetch(query)
        return [ContentItem.from_row(dict(row)) for row in rows]

    async def _save_heuristic_score(self, item_id: int | None, score: int):
        """Save heuristic score to content item."""
        await self.db.pool.execute(
            """
            UPDATE content_items
            SET heuristic_score = $2
            WHERE id = $1
            """,
            item_id,
            score,
        )

    async def _save_llm_score(self, item_id: int | None, score: int):
        """Save LLM quality score to content item."""
        await self.db.pool.execute(
            """
            UPDATE content_items
            SET llm_quality_score = $2
            WHERE id = $1
            """,
            item_id,
            score,
        )

    async def _get_heuristic_score(self, item_id: int | None) -> int:
        """Get heuristic score for an item."""
        row = await self.db.pool.fetchrow(
            "SELECT heuristic_score FROM content_items WHERE id = $1",
            item_id,
        )
        return row["heuristic_score"] if row else 0

    async def _mark_summary_excluded(self, item_id: int | None, reason: str):
        """Mark item as excluded from summary."""
        await self.db.pool.execute(
            """
            UPDATE content_items
            SET summary_excluded = TRUE,
                exclusion_reason = $2
            WHERE id = $1
            """,
            item_id,
            reason,
        )

    async def _create_assessment_record(
        self,
        item_id: int | None,
        assessment_type: str,
        score: int,
        details: dict,
    ):
        """Create triage assessment record for lineage."""
        try:
            await self.db.pool.execute(
                """
                INSERT INTO triage_assessments
                    (content_item_id, assessment_type, score, details, created_at)
                VALUES ($1, $2, $3, $4, NOW())
                """,
                item_id,
                assessment_type,
                score,
                json.dumps(details),
            )
        except Exception as e:
            # Table may not exist yet
            logger.debug(f"Could not create assessment record: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# Module-level functions
# ─────────────────────────────────────────────────────────────────────────────


async def run_heuristic_triage(
    scenario_id: Optional[str] = None,
    limit: int = 50,
) -> list[dict]:
    """Run heuristic triage on content items.

    Args:
        scenario_id: Optional filter for test isolation
        limit: Maximum items to process

    Returns:
        List of triage results
    """
    config = TriageConfig.from_env()
    worker_config = WorkerConfig.from_env()

    db = await Database.connect(
        worker_config.db_url,
        min_size=1,
        max_size=2,
    )

    try:
        pipeline = TriagePipeline(config, db)
        return await pipeline.run_heuristic_triage(scenario_id, limit)
    finally:
        await db.close()


async def run_llm_triage(
    scenario_id: Optional[str] = None,
    limit: int = 20,
) -> list[dict]:
    """Run LLM triage on content items (assessment via Engine/Complete — no
    optillm endpoint parameter: Engine-First, no bypass).

    Args:
        scenario_id: Optional filter for test isolation
        limit: Maximum items to process

    Returns:
        List of triage results
    """
    config = TriageConfig.from_env()
    worker_config = WorkerConfig.from_env()

    db = await Database.connect(
        worker_config.db_url,
        min_size=1,
        max_size=2,
    )

    try:
        pipeline = TriagePipeline(config, db)
        return await pipeline.run_llm_triage(scenario_id, limit)
    finally:
        await pipeline.close()
        await db.close()
