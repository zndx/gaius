"""Model lineage tracking for merged models.

Tracks the provenance of merged models, linking them to their
parent models and recording merge operations in the database.
Integrates with the existing lineage_events table and agent_versions.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ModelLineageEntry:
    """A single entry in model lineage."""

    model_id: str  # Unique identifier for this model
    model_path: str | None  # Local path to model weights
    hf_model_id: str | None  # HuggingFace model ID if applicable

    # Lineage
    parent_ids: list[str] = field(default_factory=list)  # Parent model IDs
    merge_method: str | None = None  # Method used to create (if merged)
    merge_config: dict[str, Any] = field(default_factory=dict)

    # Metadata
    created_at: datetime = field(default_factory=datetime.utcnow)
    created_by: str = "gaius"

    # Evaluation
    eval_scores: dict[str, float] = field(default_factory=dict)
    best_score: float | None = None
    eval_count: int = 0

    # Agent association
    agent_id: str | None = None  # If this model is used by an agent
    agent_version_id: str | None = None

    # Tags for organization
    tags: list[str] = field(default_factory=list)
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "model_path": self.model_path,
            "hf_model_id": self.hf_model_id,
            "parent_ids": self.parent_ids,
            "merge_method": self.merge_method,
            "merge_config": self.merge_config,
            "created_at": self.created_at.isoformat(),
            "created_by": self.created_by,
            "eval_scores": self.eval_scores,
            "best_score": self.best_score,
            "eval_count": self.eval_count,
            "agent_id": self.agent_id,
            "agent_version_id": self.agent_version_id,
            "tags": self.tags,
            "notes": self.notes,
        }


class ModelLineageTracker:
    """Tracks model lineage in the database."""

    def __init__(self, db_url: str | None = None):
        """Initialize tracker.

        Args:
            db_url: Database URL (uses GAIUS_DATABASE_URL env var if not provided)
        """
        self.db_url = db_url
        self._pool = None

    async def _ensure_pool(self):
        """Ensure database connection pool is initialized."""
        if self._pool is not None:
            return

        import os

        import asyncpg

        db_url = self.db_url or os.environ.get("GAIUS_DATABASE_URL")
        if not db_url:
            raise RuntimeError("GAIUS_DATABASE_URL not set")

        self._pool = await asyncpg.create_pool(db_url, min_size=1, max_size=5)

    async def record_merge(
        self,
        merge_id: str,
        method: str,
        parent_model_ids: list[str],
        output_path: str | None,
        config: dict[str, Any],
        parent_version_ids: list[str] | None = None,
        eval_score: float | None = None,
    ) -> str:
        """Record a model merge operation.

        Uses the OpenLineage-compatible lineage_events table.

        Args:
            merge_id: Unique ID for this merge
            method: Merge method used (ties, dare, slerp, etc.)
            parent_model_ids: IDs of parent models
            output_path: Path to merged model
            config: Merge configuration
            parent_version_ids: Agent version IDs if applicable
            eval_score: Initial evaluation score if available

        Returns:
            Run ID for the lineage event
        """
        await self._ensure_pool()

        run_id = uuid.uuid4()

        # Build OpenLineage-compatible event
        inputs = [
            {"namespace": "gaius.models", "name": model_id}
            for model_id in parent_model_ids
        ]

        outputs = []
        if output_path:
            outputs.append({
                "namespace": "gaius.models",
                "name": merge_id,
                "facets": {
                    "path": output_path,
                    "method": method,
                },
            })

        facets = {
            "merge_config": config,
            "parent_version_ids": parent_version_ids or [],
            "eval_score": eval_score,
        }

        async with self._pool.acquire() as conn:
            # Record START event
            await conn.execute(
                """
                SELECT record_lineage_event(
                    $1::uuid,
                    'gaius.evolution',
                    'model_merge',
                    'START',
                    $2::jsonb,
                    $3::jsonb,
                    $4::jsonb
                )
                """,
                run_id,
                inputs,
                outputs,
                facets,
            )

            # Record COMPLETE event
            await conn.execute(
                """
                SELECT record_lineage_event(
                    $1::uuid,
                    'gaius.evolution',
                    'model_merge',
                    'COMPLETE',
                    $2::jsonb,
                    $3::jsonb,
                    $4::jsonb
                )
                """,
                run_id,
                inputs,
                outputs,
                facets,
            )

        logger.info(f"Recorded merge lineage: {merge_id} (run_id={run_id})")
        return str(run_id)

    async def get_model_lineage(self, model_id: str) -> list[dict[str, Any]]:
        """Get lineage chain for a model.

        Args:
            model_id: Model ID to trace

        Returns:
            List of lineage events from most recent to oldest
        """
        await self._ensure_pool()

        async with self._pool.acquire() as conn:
            # Find merge events that produced this model
            rows = await conn.fetch(
                """
                SELECT
                    run_id,
                    event_time,
                    run_state,
                    inputs,
                    outputs,
                    facets
                FROM lineage_events
                WHERE job_namespace = 'gaius.evolution'
                  AND job_name = 'model_merge'
                  AND outputs @> $1::jsonb
                ORDER BY event_time DESC
                """,
                [{"name": model_id}],
            )

            return [dict(row) for row in rows]

    async def get_model_descendants(self, model_id: str) -> list[str]:
        """Get all models derived from a given model.

        Args:
            model_id: Parent model ID

        Returns:
            List of descendant model IDs
        """
        await self._ensure_pool()

        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT DISTINCT
                    jsonb_array_elements(outputs)->>'name' as model_id
                FROM lineage_events
                WHERE job_namespace = 'gaius.evolution'
                  AND job_name = 'model_merge'
                  AND run_state = 'COMPLETE'
                  AND inputs @> $1::jsonb
                """,
                [{"name": model_id}],
            )

            return [row["model_id"] for row in rows if row["model_id"]]

    async def link_to_agent_version(
        self,
        model_id: str,
        agent_id: str,
        version_id: str,
    ) -> None:
        """Link a merged model to an agent version.

        Updates the agent_versions table to track which model
        was used for this version.

        Args:
            model_id: Model ID
            agent_id: Agent ID
            version_id: Version ID
        """
        await self._ensure_pool()

        async with self._pool.acquire() as conn:
            # Update agent version with model reference
            await conn.execute(
                """
                UPDATE agent_versions
                SET config = config || jsonb_build_object('merged_model_id', $1)
                WHERE version_id = $2
                """,
                model_id,
                version_id,
            )

        logger.info(f"Linked model {model_id} to agent {agent_id} version {version_id}")

    async def get_best_models_for_merging(
        self,
        agent_id: str,
        min_score: float = 0.7,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """Get best performing model versions suitable for merging.

        Args:
            agent_id: Agent to get versions for
            min_score: Minimum average score threshold
            limit: Maximum number of versions to return

        Returns:
            List of version info dicts with model IDs
        """
        await self._ensure_pool()

        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT
                    version_id,
                    config,
                    avg_overall_score,
                    evaluation_count,
                    created_at
                FROM agent_versions
                WHERE agent_id = $1
                  AND avg_overall_score >= $2
                  AND evaluation_count >= 3
                ORDER BY avg_overall_score DESC
                LIMIT $3
                """,
                agent_id,
                min_score,
                limit,
            )

            return [
                {
                    "version_id": row["version_id"],
                    "config": dict(row["config"]) if row["config"] else {},
                    "score": row["avg_overall_score"],
                    "eval_count": row["evaluation_count"],
                    "created_at": row["created_at"],
                }
                for row in rows
            ]

    async def record_evaluation(
        self,
        merge_id: str,
        score: float,
        queries_evaluated: int,
        improvement_percent: float,
    ) -> None:
        """Record evaluation results for a merged model.

        Updates the lineage event with evaluation results.

        Args:
            merge_id: Merge ID to update
            score: Evaluation score achieved
            queries_evaluated: Number of held-out queries used
            improvement_percent: Improvement over baseline
        """
        await self._ensure_pool()

        async with self._pool.acquire() as conn:
            # Find the most recent COMPLETE event for this merge
            row = await conn.fetchrow(
                """
                SELECT run_id, facets
                FROM lineage_events
                WHERE job_namespace = 'gaius.evolution'
                  AND job_name = 'model_merge'
                  AND run_state = 'COMPLETE'
                  AND outputs @> $1::jsonb
                ORDER BY event_time DESC
                LIMIT 1
                """,
                [{"name": merge_id}],
            )

            if not row:
                logger.warning(f"No lineage event found for merge {merge_id}")
                return

            # Update facets with evaluation results
            run_id = row["run_id"]
            facets = dict(row["facets"]) if row["facets"] else {}
            facets["evaluation"] = {
                "score": score,
                "queries_evaluated": queries_evaluated,
                "improvement_percent": improvement_percent,
                "evaluated_at": datetime.utcnow().isoformat(),
            }

            await conn.execute(
                """
                UPDATE lineage_events
                SET facets = $1::jsonb
                WHERE run_id = $2
                  AND run_state = 'COMPLETE'
                """,
                facets,
                run_id,
            )

            logger.info(
                f"Recorded evaluation for merge {merge_id}: "
                f"score={score:.3f}, improvement={improvement_percent:.1f}%"
            )


# ═══════════════════════════════════════════════════════════════════════════════
# Module-level API
# ═══════════════════════════════════════════════════════════════════════════════

_tracker: ModelLineageTracker | None = None


def get_lineage_tracker() -> ModelLineageTracker:
    """Get or create the lineage tracker singleton."""
    global _tracker
    if _tracker is None:
        _tracker = ModelLineageTracker()
    return _tracker


async def record_merge_lineage(
    merge_id: str,
    method: str,
    parent_model_ids: list[str],
    output_path: str | None = None,
    config: dict[str, Any] | None = None,
    parent_version_ids: list[str] | None = None,
) -> str:
    """Convenience function to record merge lineage."""
    tracker = get_lineage_tracker()
    return await tracker.record_merge(
        merge_id=merge_id,
        method=method,
        parent_model_ids=parent_model_ids,
        output_path=output_path,
        config=config or {},
        parent_version_ids=parent_version_ids,
    )
