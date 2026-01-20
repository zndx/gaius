"""Metaflow query client for operational insights.

Provides read-only access to Metaflow run history stored in meta.flow_runs.
Used by MetaAgent Judge for situational awareness about pipeline operations.

Queries:
- List recent flow runs by type
- Get flow run details
- Get flow statistics (success rates, durations)
- List available flow types
"""

import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import asyncpg

logger = logging.getLogger(__name__)


@dataclass
class FlowRunSummary:
    """Summary of a flow run."""

    run_id: str
    flow_type: str
    status: str
    started_at: datetime | None
    completed_at: datetime | None
    duration_ms: int | None
    inputs_count: int
    outputs_count: int


@dataclass
class FlowStats:
    """Statistics for a flow type."""

    flow_type: str
    total_runs: int
    completed_runs: int
    failed_runs: int
    running_runs: int
    avg_duration_ms: float | None
    success_rate: float


class MetaflowQueryClient:
    """Read-only client for querying Metaflow run history.

    Features:
    - Query flow_runs table in meta schema
    - Get run history by flow type
    - Calculate success rates and durations
    - No write operations (read-only for situational awareness)

    Guru Meditation Codes:
    - #MF.00000001.DBNOTCONN - Database connection failed
    - #MF.00000002.QUERYERR - Query execution failed
    """

    def __init__(self, database_url: str | None = None):
        """Initialize Metaflow query client.

        Args:
            database_url: PostgreSQL connection URL (default from env)
        """
        self.database_url = database_url or os.environ.get(
            "DATABASE_URL",
            "postgres://gaius:gaius@localhost:5438/zndx_gaius",
        )
        self._pool: asyncpg.Pool | None = None

    async def _get_pool(self) -> asyncpg.Pool:
        """Get or create connection pool."""
        if self._pool is None:
            try:
                self._pool = await asyncpg.create_pool(
                    self.database_url,
                    min_size=1,
                    max_size=5,
                    command_timeout=30,
                )
            except Exception as e:
                logger.error(f"[#MF.00000001.DBNOTCONN] Database connection failed: {e}")
                raise
        return self._pool

    async def list_flow_types(self) -> list[dict[str, Any]]:
        """List all flow types with run counts.

        Returns:
            List of flow types with statistics
        """
        pool = await self._get_pool()
        try:
            rows = await pool.fetch("""
                SELECT
                    flow_type,
                    COUNT(*) as total_runs,
                    COUNT(*) FILTER (WHERE status = 'completed') as completed,
                    COUNT(*) FILTER (WHERE status = 'failed') as failed,
                    COUNT(*) FILTER (WHERE status = 'running') as running,
                    MAX(started_at) as last_run
                FROM meta.flow_runs
                GROUP BY flow_type
                ORDER BY total_runs DESC
            """)
            return [
                {
                    "flow_type": row["flow_type"],
                    "total_runs": row["total_runs"],
                    "completed": row["completed"],
                    "failed": row["failed"],
                    "running": row["running"],
                    "last_run": row["last_run"].isoformat() if row["last_run"] else None,
                }
                for row in rows
            ]
        except Exception as e:
            logger.error(f"[#MF.00000002.QUERYERR] Query failed: {e}")
            return []

    async def list_recent_runs(
        self,
        flow_type: str | None = None,
        status: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """List recent flow runs with optional filtering.

        Args:
            flow_type: Filter by flow type (e.g., "research", "arxiv")
            status: Filter by status (completed, failed, running)
            limit: Maximum runs to return

        Returns:
            List of flow run summaries
        """
        pool = await self._get_pool()
        try:
            # Build query with optional filters
            conditions = []
            params = []
            param_idx = 1

            if flow_type:
                conditions.append(f"flow_type = ${param_idx}")
                params.append(flow_type)
                param_idx += 1

            if status:
                conditions.append(f"status = ${param_idx}")
                params.append(status)
                param_idx += 1

            where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
            params.append(limit)

            query = f"""
                SELECT
                    run_id::text,
                    flow_type,
                    status,
                    started_at,
                    completed_at,
                    duration_ms,
                    inputs_count,
                    outputs_count,
                    metadata
                FROM meta.flow_runs
                {where_clause}
                ORDER BY started_at DESC NULLS LAST
                LIMIT ${param_idx}
            """

            rows = await pool.fetch(query, *params)
            return [
                {
                    "run_id": row["run_id"],
                    "flow_type": row["flow_type"],
                    "status": row["status"],
                    "started_at": row["started_at"].isoformat() if row["started_at"] else None,
                    "completed_at": row["completed_at"].isoformat() if row["completed_at"] else None,
                    "duration_ms": row["duration_ms"],
                    "inputs_count": row["inputs_count"],
                    "outputs_count": row["outputs_count"],
                }
                for row in rows
            ]
        except Exception as e:
            logger.error(f"[#MF.00000002.QUERYERR] Query failed: {e}")
            return []

    async def get_run_details(self, run_id: str) -> dict[str, Any] | None:
        """Get detailed information about a specific flow run.

        Args:
            run_id: UUID of the flow run

        Returns:
            Flow run details including metadata, or None if not found
        """
        pool = await self._get_pool()
        try:
            row = await pool.fetchrow(
                """
                SELECT
                    run_id::text,
                    flow_type,
                    status,
                    started_at,
                    completed_at,
                    duration_ms,
                    inputs_count,
                    outputs_count,
                    metadata
                FROM meta.flow_runs
                WHERE run_id = $1::uuid
                """,
                run_id,
            )
            if not row:
                return None

            return {
                "run_id": row["run_id"],
                "flow_type": row["flow_type"],
                "status": row["status"],
                "started_at": row["started_at"].isoformat() if row["started_at"] else None,
                "completed_at": row["completed_at"].isoformat() if row["completed_at"] else None,
                "duration_ms": row["duration_ms"],
                "inputs_count": row["inputs_count"],
                "outputs_count": row["outputs_count"],
                "metadata": dict(row["metadata"]) if row["metadata"] else {},
            }
        except Exception as e:
            logger.error(f"[#MF.00000002.QUERYERR] Query failed: {e}")
            return None

    async def get_flow_stats(
        self,
        flow_type: str | None = None,
        hours: int = 24,
    ) -> dict[str, Any]:
        """Get flow statistics over a time period.

        Args:
            flow_type: Specific flow type or None for all
            hours: Time window in hours (default 24)

        Returns:
            Statistics including counts, success rates, durations
        """
        pool = await self._get_pool()
        try:
            if flow_type:
                row = await pool.fetchrow(
                    """
                    SELECT
                        COUNT(*) as total_runs,
                        COUNT(*) FILTER (WHERE status = 'completed') as completed,
                        COUNT(*) FILTER (WHERE status = 'failed') as failed,
                        COUNT(*) FILTER (WHERE status = 'running') as running,
                        AVG(duration_ms) FILTER (WHERE status = 'completed') as avg_duration_ms,
                        MIN(duration_ms) FILTER (WHERE status = 'completed') as min_duration_ms,
                        MAX(duration_ms) FILTER (WHERE status = 'completed') as max_duration_ms,
                        SUM(inputs_count) as total_inputs,
                        SUM(outputs_count) as total_outputs
                    FROM meta.flow_runs
                    WHERE flow_type = $1
                      AND started_at >= NOW() - INTERVAL '%s hours'
                    """ % hours,
                    flow_type,
                )
            else:
                row = await pool.fetchrow(
                    """
                    SELECT
                        COUNT(*) as total_runs,
                        COUNT(*) FILTER (WHERE status = 'completed') as completed,
                        COUNT(*) FILTER (WHERE status = 'failed') as failed,
                        COUNT(*) FILTER (WHERE status = 'running') as running,
                        AVG(duration_ms) FILTER (WHERE status = 'completed') as avg_duration_ms,
                        MIN(duration_ms) FILTER (WHERE status = 'completed') as min_duration_ms,
                        MAX(duration_ms) FILTER (WHERE status = 'completed') as max_duration_ms,
                        SUM(inputs_count) as total_inputs,
                        SUM(outputs_count) as total_outputs
                    FROM meta.flow_runs
                    WHERE started_at >= NOW() - INTERVAL '%s hours'
                    """ % hours
                )

            total = row["total_runs"] or 0
            completed = row["completed"] or 0
            success_rate = (completed / total * 100) if total > 0 else 0.0

            return {
                "flow_type": flow_type or "all",
                "time_window_hours": hours,
                "total_runs": total,
                "completed": completed,
                "failed": row["failed"] or 0,
                "running": row["running"] or 0,
                "success_rate_pct": round(success_rate, 1),
                "avg_duration_ms": round(row["avg_duration_ms"]) if row["avg_duration_ms"] else None,
                "min_duration_ms": row["min_duration_ms"],
                "max_duration_ms": row["max_duration_ms"],
                "total_inputs": row["total_inputs"] or 0,
                "total_outputs": row["total_outputs"] or 0,
            }
        except Exception as e:
            logger.error(f"[#MF.00000002.QUERYERR] Query failed: {e}")
            return {
                "flow_type": flow_type or "all",
                "error": str(e),
            }

    async def get_status_summary(self) -> dict[str, Any]:
        """Get overall Metaflow status summary.

        Returns:
            Summary with flow types, recent activity, health indicators
        """
        pool = await self._get_pool()
        try:
            # Get flow type summary
            flow_types = await self.list_flow_types()

            # Get recent runs (last 24h)
            stats_24h = await self.get_flow_stats(hours=24)

            # Get currently running
            running_rows = await pool.fetch("""
                SELECT flow_type, run_id::text, started_at
                FROM meta.flow_runs
                WHERE status = 'running'
                ORDER BY started_at DESC
                LIMIT 10
            """)

            # Get recent failures (last 1h)
            failure_rows = await pool.fetch("""
                SELECT flow_type, run_id::text, completed_at, metadata->>'error' as error
                FROM meta.flow_runs
                WHERE status = 'failed'
                  AND completed_at >= NOW() - INTERVAL '1 hour'
                ORDER BY completed_at DESC
                LIMIT 5
            """)

            return {
                "flow_types": flow_types,
                "stats_24h": stats_24h,
                "currently_running": [
                    {
                        "flow_type": row["flow_type"],
                        "run_id": row["run_id"],
                        "started_at": row["started_at"].isoformat() if row["started_at"] else None,
                    }
                    for row in running_rows
                ],
                "recent_failures": [
                    {
                        "flow_type": row["flow_type"],
                        "run_id": row["run_id"],
                        "completed_at": row["completed_at"].isoformat() if row["completed_at"] else None,
                        "error": row["error"][:200] if row["error"] else None,
                    }
                    for row in failure_rows
                ],
            }
        except Exception as e:
            logger.error(f"[#MF.00000002.QUERYERR] Query failed: {e}")
            return {"error": str(e)}

    async def close(self) -> None:
        """Close connection pool."""
        if self._pool:
            await self._pool.close()
            self._pool = None


# Module-level singleton
_metaflow_client: MetaflowQueryClient | None = None


def get_metaflow_client() -> MetaflowQueryClient:
    """Get or create Metaflow query client singleton."""
    global _metaflow_client
    if _metaflow_client is None:
        _metaflow_client = MetaflowQueryClient()
    return _metaflow_client


async def reset_metaflow_client() -> None:
    """Reset Metaflow client singleton (for testing)."""
    global _metaflow_client
    if _metaflow_client:
        await _metaflow_client.close()
    _metaflow_client = None
