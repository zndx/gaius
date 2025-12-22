"""Agent version control for configuration management.

Tracks agent configurations, performance metrics, and enables
rollback to previous high-performing versions.

Usage:
    from gaius.models import get_version_manager, AgentConfig

    manager = get_version_manager()

    # Save current config
    version = await manager.save_version(
        agent_id="leader",
        config=AgentConfig(
            system_prompt="...",
            temperature=0.7,
            model="Qwen/QwQ-32B",
        ),
        metrics={"accuracy": 0.85, "coherence": 0.90},
    )

    # Get best performing version
    best = await manager.get_best_version("leader", metric="accuracy")

    # Rollback
    await manager.set_active_version("leader", best.version_id)
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
import hashlib
import json


@dataclass
class AgentConfig:
    """Configuration for an agent."""

    # Core settings
    system_prompt: str
    model: str = "Qwen/Qwen3-Coder-30B-A3B-Instruct"
    temperature: float = 0.7
    max_tokens: int = 2048

    # Optional settings
    top_p: float = 0.9
    frequency_penalty: float = 0.0
    presence_penalty: float = 0.0

    # Task-specific
    task_type: str | None = None
    optillm_technique: str | None = None
    technique_params: dict[str, Any] = field(default_factory=dict)  # e.g., {"n": 5} for BON

    # Metadata
    description: str = ""
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "system_prompt": self.system_prompt,
            "model": self.model,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "top_p": self.top_p,
            "frequency_penalty": self.frequency_penalty,
            "presence_penalty": self.presence_penalty,
            "task_type": self.task_type,
            "optillm_technique": self.optillm_technique,
            "technique_params": self.technique_params,
            "description": self.description,
            "tags": self.tags,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "AgentConfig":
        """Create from dictionary."""
        return cls(
            system_prompt=data["system_prompt"],
            model=data.get("model", "Qwen/Qwen3-Coder-30B-A3B-Instruct"),
            temperature=data.get("temperature", 0.7),
            max_tokens=data.get("max_tokens", 2048),
            top_p=data.get("top_p", 0.9),
            frequency_penalty=data.get("frequency_penalty", 0.0),
            presence_penalty=data.get("presence_penalty", 0.0),
            task_type=data.get("task_type"),
            optillm_technique=data.get("optillm_technique"),
            technique_params=data.get("technique_params", {}),
            description=data.get("description", ""),
            tags=data.get("tags", []),
        )

    def config_hash(self) -> str:
        """Generate hash of configuration for deduplication."""
        content = json.dumps(self.to_dict(), sort_keys=True)
        return hashlib.sha256(content.encode()).hexdigest()[:16]


@dataclass
class AgentVersion:
    """A versioned agent configuration with performance tracking."""

    version_id: str
    agent_id: str
    config: AgentConfig

    # Version metadata
    created_at: datetime = field(default_factory=datetime.now)
    created_by: str = "system"
    parent_version: str | None = None
    is_active: bool = False

    # Performance metrics (from evaluations)
    metrics: dict[str, float] = field(default_factory=dict)
    evaluation_count: int = 0

    # Aggregated scores
    avg_overall_score: float = 0.0
    best_overall_score: float = 0.0

    # Notes
    change_notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for storage."""
        return {
            "version_id": self.version_id,
            "agent_id": self.agent_id,
            "config": self.config.to_dict(),
            "created_at": self.created_at.isoformat(),
            "created_by": self.created_by,
            "parent_version": self.parent_version,
            "is_active": self.is_active,
            "metrics": self.metrics,
            "evaluation_count": self.evaluation_count,
            "avg_overall_score": self.avg_overall_score,
            "best_overall_score": self.best_overall_score,
            "change_notes": self.change_notes,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "AgentVersion":
        """Create from dictionary."""
        version = cls(
            version_id=data["version_id"],
            agent_id=data["agent_id"],
            config=AgentConfig.from_dict(data["config"]),
            created_by=data.get("created_by", "system"),
            parent_version=data.get("parent_version"),
            is_active=data.get("is_active", False),
            metrics=data.get("metrics", {}),
            evaluation_count=data.get("evaluation_count", 0),
            avg_overall_score=data.get("avg_overall_score", 0.0),
            best_overall_score=data.get("best_overall_score", 0.0),
            change_notes=data.get("change_notes", ""),
        )

        if "created_at" in data:
            version.created_at = datetime.fromisoformat(data["created_at"])

        return version


class VersionManager:
    """Manages agent versions with database persistence."""

    def __init__(self, db_url: str | None = None):
        """Initialize version manager.

        Args:
            db_url: PostgreSQL connection URL
        """
        self._db_url = db_url
        self._pool = None

    async def _get_pool(self):
        """Get database connection pool."""
        if self._pool is None:
            import asyncpg

            if self._db_url is None:
                from ..core.config import get_config
                config = get_config()
                self._db_url = config.database.url

            self._pool = await asyncpg.create_pool(self._db_url, min_size=1, max_size=5)

        return self._pool

    async def save_version(
        self,
        agent_id: str,
        config: AgentConfig,
        metrics: dict[str, float] | None = None,
        parent_version: str | None = None,
        change_notes: str = "",
        created_by: str = "system",
        set_active: bool = True,
    ) -> AgentVersion:
        """Save a new agent version.

        Args:
            agent_id: Agent identifier
            config: Agent configuration
            metrics: Performance metrics
            parent_version: ID of parent version
            change_notes: Description of changes
            created_by: Who created this version
            set_active: If True, set this as the active version

        Returns:
            Created AgentVersion
        """
        import uuid

        version_id = f"{agent_id}-{config.config_hash()}-{uuid.uuid4().hex[:8]}"

        version = AgentVersion(
            version_id=version_id,
            agent_id=agent_id,
            config=config,
            created_by=created_by,
            parent_version=parent_version,
            is_active=set_active,
            metrics=metrics or {},
            change_notes=change_notes,
        )

        pool = await self._get_pool()

        async with pool.acquire() as conn:
            # Deactivate current active version if setting new active
            if set_active:
                await conn.execute(
                    """
                    UPDATE agent_versions
                    SET is_active = false
                    WHERE agent_id = $1 AND is_active = true
                    """,
                    agent_id,
                )

            # Insert new version
            await conn.execute(
                """
                INSERT INTO agent_versions (
                    version_id, agent_id, config, created_at, created_by,
                    parent_version, is_active, metrics, evaluation_count,
                    avg_overall_score, best_overall_score, change_notes
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
                """,
                version.version_id,
                version.agent_id,
                json.dumps(version.config.to_dict()),
                version.created_at,
                version.created_by,
                version.parent_version,
                version.is_active,
                json.dumps(version.metrics),
                version.evaluation_count,
                version.avg_overall_score,
                version.best_overall_score,
                version.change_notes,
            )

        return version

    async def get_version(self, version_id: str) -> AgentVersion | None:
        """Get a specific version by ID."""
        pool = await self._get_pool()

        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM agent_versions WHERE version_id = $1",
                version_id,
            )

            if row is None:
                return None

            return self._row_to_version(row)

    async def get_active_version(self, agent_id: str) -> AgentVersion | None:
        """Get the active version for an agent."""
        pool = await self._get_pool()

        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT * FROM agent_versions
                WHERE agent_id = $1 AND is_active = true
                """,
                agent_id,
            )

            if row is None:
                return None

            return self._row_to_version(row)

    async def get_versions(
        self,
        agent_id: str,
        limit: int = 20,
        include_inactive: bool = True,
    ) -> list[AgentVersion]:
        """Get version history for an agent."""
        pool = await self._get_pool()

        async with pool.acquire() as conn:
            if include_inactive:
                rows = await conn.fetch(
                    """
                    SELECT * FROM agent_versions
                    WHERE agent_id = $1
                    ORDER BY created_at DESC
                    LIMIT $2
                    """,
                    agent_id,
                    limit,
                )
            else:
                rows = await conn.fetch(
                    """
                    SELECT * FROM agent_versions
                    WHERE agent_id = $1 AND is_active = true
                    ORDER BY created_at DESC
                    LIMIT $2
                    """,
                    agent_id,
                    limit,
                )

            return [self._row_to_version(row) for row in rows]

    async def get_best_version(
        self,
        agent_id: str,
        metric: str = "avg_overall_score",
        min_evaluations: int = 3,
    ) -> AgentVersion | None:
        """Get the best performing version for an agent.

        Args:
            agent_id: Agent identifier
            metric: Metric to rank by (from metrics dict or avg_overall_score)
            min_evaluations: Minimum evaluations required

        Returns:
            Best performing AgentVersion or None
        """
        pool = await self._get_pool()

        async with pool.acquire() as conn:
            # For standard metrics
            if metric in ("avg_overall_score", "best_overall_score"):
                row = await conn.fetchrow(
                    f"""
                    SELECT * FROM agent_versions
                    WHERE agent_id = $1 AND evaluation_count >= $2
                    ORDER BY {metric} DESC
                    LIMIT 1
                    """,
                    agent_id,
                    min_evaluations,
                )
            else:
                # For custom metrics in JSON
                row = await conn.fetchrow(
                    """
                    SELECT * FROM agent_versions
                    WHERE agent_id = $1 AND evaluation_count >= $2
                    ORDER BY (metrics->>$3)::float DESC NULLS LAST
                    LIMIT 1
                    """,
                    agent_id,
                    min_evaluations,
                    metric,
                )

            if row is None:
                return None

            return self._row_to_version(row)

    async def set_active_version(self, agent_id: str, version_id: str) -> bool:
        """Set a version as the active version (rollback).

        Args:
            agent_id: Agent identifier
            version_id: Version to activate

        Returns:
            True if successful
        """
        pool = await self._get_pool()

        async with pool.acquire() as conn:
            async with conn.transaction():
                # Deactivate current
                await conn.execute(
                    """
                    UPDATE agent_versions
                    SET is_active = false
                    WHERE agent_id = $1 AND is_active = true
                    """,
                    agent_id,
                )

                # Activate target
                result = await conn.execute(
                    """
                    UPDATE agent_versions
                    SET is_active = true
                    WHERE version_id = $1 AND agent_id = $2
                    """,
                    version_id,
                    agent_id,
                )

                return result == "UPDATE 1"

    async def update_metrics(
        self,
        version_id: str,
        evaluation_score: float,
        dimension_scores: dict[str, float] | None = None,
    ) -> None:
        """Update metrics for a version after evaluation.

        Args:
            version_id: Version to update
            evaluation_score: Overall score from this evaluation
            dimension_scores: Individual dimension scores
        """
        pool = await self._get_pool()

        async with pool.acquire() as conn:
            # Get current metrics
            row = await conn.fetchrow(
                """
                SELECT metrics, evaluation_count, avg_overall_score, best_overall_score
                FROM agent_versions WHERE version_id = $1
                """,
                version_id,
            )

            if row is None:
                return

            current_metrics = json.loads(row["metrics"]) if row["metrics"] else {}
            eval_count = row["evaluation_count"] or 0
            current_avg = row["avg_overall_score"] or 0.0
            current_best = row["best_overall_score"] or 0.0

            # Update running average
            new_count = eval_count + 1
            new_avg = (current_avg * eval_count + evaluation_score) / new_count
            new_best = max(current_best, evaluation_score)

            # Update dimension metrics (running averages)
            if dimension_scores:
                for dim, score in dimension_scores.items():
                    if dim in current_metrics:
                        current_metrics[dim] = (
                            current_metrics[dim] * eval_count + score
                        ) / new_count
                    else:
                        current_metrics[dim] = score

            await conn.execute(
                """
                UPDATE agent_versions
                SET metrics = $1, evaluation_count = $2,
                    avg_overall_score = $3, best_overall_score = $4
                WHERE version_id = $5
                """,
                json.dumps(current_metrics),
                new_count,
                new_avg,
                new_best,
                version_id,
            )

    async def compare_versions(
        self,
        version_ids: list[str],
    ) -> dict[str, dict[str, Any]]:
        """Compare multiple versions.

        Args:
            version_ids: List of version IDs to compare

        Returns:
            Dict mapping version_id to comparison data
        """
        result = {}

        for vid in version_ids:
            version = await self.get_version(vid)
            if version:
                result[vid] = {
                    "config": version.config.to_dict(),
                    "metrics": version.metrics,
                    "avg_score": version.avg_overall_score,
                    "best_score": version.best_overall_score,
                    "eval_count": version.evaluation_count,
                    "created_at": version.created_at.isoformat(),
                }

        return result

    def _row_to_version(self, row) -> AgentVersion:
        """Convert database row to AgentVersion."""
        config_dict = json.loads(row["config"]) if row["config"] else {}
        metrics = json.loads(row["metrics"]) if row["metrics"] else {}

        return AgentVersion(
            version_id=row["version_id"],
            agent_id=row["agent_id"],
            config=AgentConfig.from_dict(config_dict),
            created_at=row["created_at"],
            created_by=row["created_by"] or "system",
            parent_version=row["parent_version"],
            is_active=row["is_active"],
            metrics=metrics,
            evaluation_count=row["evaluation_count"] or 0,
            avg_overall_score=row["avg_overall_score"] or 0.0,
            best_overall_score=row["best_overall_score"] or 0.0,
            change_notes=row["change_notes"] or "",
        )

    async def close(self) -> None:
        """Close database connections."""
        if self._pool:
            await self._pool.close()
            self._pool = None


# ═══════════════════════════════════════════════════════════════════════════════
# Module-level API
# ═══════════════════════════════════════════════════════════════════════════════

_manager: VersionManager | None = None


def get_version_manager() -> VersionManager:
    """Get or create the version manager singleton."""
    global _manager
    if _manager is None:
        _manager = VersionManager()
    return _manager
