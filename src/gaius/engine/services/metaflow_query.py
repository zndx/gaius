"""Metaflow query client for operational insights.

Read-only access to the LIVE Metaflow metadata service store — the
``metaflow`` database the metaflow-service pod writes (``runs_v3`` /
``steps_v3``). Used by MetaAgent Judge and the Metaflow Stack health
check for situational awareness about pipeline operations.

History: this client originally read ``meta.flow_runs`` in the gaius DB —
a table nothing has written since flows moved to the platform metadata
service. That made every reader (health check, MCP metaflow_* tools)
report "no runs" while flows ran fine (#MF.00000003.STACKDOWN false
alarm, discovered 2026-08-31). The service store is the truth.

Status derivation (the service schema has no status column):
- ``completed``: the run's ``end`` step exists (the flow reached end);
- ``running``: no end step yet, but the heartbeat is fresh (<15 min);
- ``failed``: no end step and the heartbeat has gone stale.

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

# The LIVE metadata store: since flows moved to the platform profile
# (~2026-07-26) they register through the SIGNALS metaflow service, whose
# store is the signals-side Postgres `metaflow` DB. (The gaius-local
# service on :30180 / devenv-postgres:5444 still serves its pre-platform
# history and stopped receiving writes then.) Override with
# GAIUS_METAFLOW_DB_URL when the port shifts.
_DEFAULT_METAFLOW_DB_URL = "postgres://signals:signals@127.0.0.1:5455/metaflow"

# A run with no end step and no heartbeat for this long is failed.
_HEARTBEAT_FRESH_S = 900

# last_heartbeat_ts is epoch seconds; ts_epoch is epoch millis. Normalize
# defensively in SQL (values > ~2001-09 in millis are unambiguous).
_HB_SECONDS_SQL = (
    "CASE WHEN r.last_heartbeat_ts > 100000000000 "
    "THEN r.last_heartbeat_ts / 1000 ELSE r.last_heartbeat_ts END"
)

_STATUS_SQL = f"""
    CASE
        WHEN e.step_name IS NOT NULL THEN 'completed'
        WHEN COALESCE({_HB_SECONDS_SQL}, r.ts_epoch / 1000)
             > EXTRACT(EPOCH FROM NOW()) - {_HEARTBEAT_FRESH_S}
            THEN 'running'
        ELSE 'failed'
    END
"""

# Completed duration: end-step start minus run start. For running/failed
# runs the last heartbeat bounds the duration; NULL when unknowable.
_DURATION_SQL = f"""
    CASE
        WHEN e.step_name IS NOT NULL THEN e.ts_epoch - r.ts_epoch
        WHEN r.last_heartbeat_ts IS NOT NULL
            THEN ({_HB_SECONDS_SQL}) * 1000 - r.ts_epoch
        ELSE NULL
    END
"""

_END_JOIN = (
    "LEFT JOIN steps_v3 e ON e.flow_id = r.flow_id "
    "AND e.run_number = r.run_number AND e.step_name = 'end'"
)


def _ms_to_iso(ms: int | None) -> str | None:
    if not ms:
        return None
    return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc).isoformat()


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
    """Read-only client for the live Metaflow metadata store.

    Features:
    - Query runs_v3/steps_v3 in the metaflow-service database
    - Get run history by flow (run_id is the pathspec ``Flow/run_number``)
    - Calculate success rates and durations (end-step derivation)
    - No write operations (read-only for situational awareness)

    Guru Meditation Codes:
    - #MF.00000001.DBNOTCONN - Database connection failed
    - #MF.00000002.QUERYERR - Query execution failed
    """

    def __init__(self, database_url: str | None = None):
        """Initialize Metaflow query client.

        Args:
            database_url: PostgreSQL URL of the metaflow-service store
                (default env GAIUS_METAFLOW_DB_URL, else the signals-side
                Postgres ``metaflow`` database).
        """
        self.database_url = (
            database_url
            or os.environ.get("GAIUS_METAFLOW_DB_URL")
            or _DEFAULT_METAFLOW_DB_URL
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
            rows = await pool.fetch(f"""
                SELECT
                    r.flow_id AS flow_type,
                    COUNT(*) AS total_runs,
                    COUNT(*) FILTER (WHERE {_STATUS_SQL} = 'completed') AS completed,
                    COUNT(*) FILTER (WHERE {_STATUS_SQL} = 'failed') AS failed,
                    COUNT(*) FILTER (WHERE {_STATUS_SQL} = 'running') AS running,
                    MAX(r.ts_epoch) AS last_run_ms
                FROM runs_v3 r
                {_END_JOIN}
                GROUP BY r.flow_id
                ORDER BY total_runs DESC
            """)
            return [
                {
                    "flow_type": row["flow_type"],
                    "total_runs": row["total_runs"],
                    "completed": row["completed"],
                    "failed": row["failed"],
                    "running": row["running"],
                    "last_run": _ms_to_iso(row["last_run_ms"]),
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
            flow_type: Filter by flow id (e.g., "ArticleCurationFlow")
            status: Filter by derived status (completed, failed, running)
            limit: Maximum runs to return

        Returns:
            List of flow run summaries (run_id is ``Flow/run_number``)
        """
        pool = await self._get_pool()
        try:
            conditions = []
            params: list[Any] = []
            param_idx = 1

            if flow_type:
                conditions.append(f"r.flow_id = ${param_idx}")
                params.append(flow_type)
                param_idx += 1

            if status:
                conditions.append(f"{_STATUS_SQL} = ${param_idx}")
                params.append(status)
                param_idx += 1

            where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
            params.append(limit)

            query = f"""
                SELECT
                    r.flow_id || '/' || r.run_number AS run_id,
                    r.flow_id AS flow_type,
                    {_STATUS_SQL} AS status,
                    r.ts_epoch AS started_ms,
                    e.ts_epoch AS completed_ms,
                    ({_DURATION_SQL})::bigint AS duration_ms
                FROM runs_v3 r
                {_END_JOIN}
                {where_clause}
                ORDER BY r.ts_epoch DESC
                LIMIT ${param_idx}
            """

            rows = await pool.fetch(query, *params)
            return [
                {
                    "run_id": row["run_id"],
                    "flow_type": row["flow_type"],
                    "status": row["status"],
                    "started_at": _ms_to_iso(row["started_ms"]),
                    "completed_at": _ms_to_iso(row["completed_ms"]),
                    "duration_ms": row["duration_ms"],
                    # Not tracked by the metadata service schema.
                    "inputs_count": None,
                    "outputs_count": None,
                }
                for row in rows
            ]
        except Exception as e:
            logger.error(f"[#MF.00000002.QUERYERR] Query failed: {e}")
            return []

    async def get_run_details(self, run_id: str) -> dict[str, Any] | None:
        """Get detailed information about a specific flow run.

        Args:
            run_id: Pathspec ``Flow/run_number`` (e.g.
                ``ArticleCurationFlow/1729``).

        Returns:
            Flow run details including tags, or None if not found
        """
        if "/" not in (run_id or ""):
            logger.error(
                f"[#MF.00000002.QUERYERR] run_id must be Flow/run_number, got {run_id!r}"
            )
            return None
        flow_id, _, run_number = run_id.partition("/")
        try:
            run_no = int(run_number)
        except ValueError:
            logger.error(
                f"[#MF.00000002.QUERYERR] run_number must be numeric, got {run_number!r}"
            )
            return None

        pool = await self._get_pool()
        try:
            row = await pool.fetchrow(
                f"""
                SELECT
                    r.flow_id || '/' || r.run_number AS run_id,
                    r.flow_id AS flow_type,
                    {_STATUS_SQL} AS status,
                    r.ts_epoch AS started_ms,
                    e.ts_epoch AS completed_ms,
                    ({_DURATION_SQL})::bigint AS duration_ms,
                    r.user_name,
                    r.tags,
                    r.system_tags
                FROM runs_v3 r
                {_END_JOIN}
                WHERE r.flow_id = $1 AND r.run_number = $2
                """,
                flow_id,
                run_no,
            )
            if not row:
                return None

            return {
                "run_id": row["run_id"],
                "flow_type": row["flow_type"],
                "status": row["status"],
                "started_at": _ms_to_iso(row["started_ms"]),
                "completed_at": _ms_to_iso(row["completed_ms"]),
                "duration_ms": row["duration_ms"],
                "inputs_count": None,
                "outputs_count": None,
                "metadata": {
                    "user_name": row["user_name"],
                    "tags": row["tags"],
                    "system_tags": row["system_tags"],
                },
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
            flow_type: Specific flow id or None for all
            hours: Time window in hours (default 24)

        Returns:
            Statistics including counts, success rates, durations
        """
        pool = await self._get_pool()
        try:
            flow_cond = "AND r.flow_id = $1" if flow_type else ""
            params = [flow_type] if flow_type else []
            row = await pool.fetchrow(
                f"""
                SELECT
                    COUNT(*) AS total_runs,
                    COUNT(*) FILTER (WHERE {_STATUS_SQL} = 'completed') AS completed,
                    COUNT(*) FILTER (WHERE {_STATUS_SQL} = 'failed') AS failed,
                    COUNT(*) FILTER (WHERE {_STATUS_SQL} = 'running') AS running,
                    AVG({_DURATION_SQL}) FILTER (WHERE e.step_name IS NOT NULL) AS avg_duration_ms,
                    MIN({_DURATION_SQL}) FILTER (WHERE e.step_name IS NOT NULL) AS min_duration_ms,
                    MAX({_DURATION_SQL}) FILTER (WHERE e.step_name IS NOT NULL) AS max_duration_ms
                FROM runs_v3 r
                {_END_JOIN}
                WHERE to_timestamp(r.ts_epoch / 1000)
                      >= NOW() - INTERVAL '{int(hours)} hours'
                  {flow_cond}
                """,
                *params,
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
                # Not tracked by the metadata service schema.
                "total_inputs": None,
                "total_outputs": None,
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
            flow_types = await self.list_flow_types()
            stats_24h = await self.get_flow_stats(hours=24)

            running_rows = await pool.fetch(f"""
                SELECT r.flow_id AS flow_type,
                       r.flow_id || '/' || r.run_number AS run_id,
                       r.ts_epoch AS started_ms
                FROM runs_v3 r
                {_END_JOIN}
                WHERE {_STATUS_SQL} = 'running'
                ORDER BY r.ts_epoch DESC
                LIMIT 10
            """)

            failure_rows = await pool.fetch(f"""
                SELECT r.flow_id AS flow_type,
                       r.flow_id || '/' || r.run_number AS run_id,
                       ({_HB_SECONDS_SQL}) * 1000 AS last_seen_ms
                FROM runs_v3 r
                {_END_JOIN}
                WHERE {_STATUS_SQL} = 'failed'
                  AND to_timestamp(r.ts_epoch / 1000) >= NOW() - INTERVAL '1 hour'
                ORDER BY r.ts_epoch DESC
                LIMIT 5
            """)

            return {
                "flow_types": flow_types,
                "stats_24h": stats_24h,
                "currently_running": [
                    {
                        "flow_type": row["flow_type"],
                        "run_id": row["run_id"],
                        "started_at": _ms_to_iso(row["started_ms"]),
                    }
                    for row in running_rows
                ],
                "recent_failures": [
                    {
                        "flow_type": row["flow_type"],
                        "run_id": row["run_id"],
                        "completed_at": _ms_to_iso(row["last_seen_ms"]),
                        # The metadata store keeps no error text; the flow's
                        # own logs / scheduled_tasks.error carry the cause.
                        "error": None,
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
