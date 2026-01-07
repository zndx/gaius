"""Job Persistence Layer - PostgreSQL job queue.

Provides durable storage for inference jobs:
- Jobs survive app restarts
- Failed jobs can be retried
- Complete audit trail of job execution

Usage:
    from gaius.inference.persistence import JobPersistence

    persistence = JobPersistence()
    await persistence.connect()

    job_id = await persistence.save_job(job)
    await persistence.update_status(job_id, JobStatus.RUNNING)
    await persistence.save_result(job_id, result)

    # On restart
    pending = await persistence.get_pending_jobs()
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any
import json
import logging

from .scheduler import Job, JobStatus, JobPriority, JobResult

logger = logging.getLogger(__name__)

# Try to import asyncpg
try:
    import asyncpg
    ASYNCPG_AVAILABLE = True
except ImportError:
    ASYNCPG_AVAILABLE = False
    logger.warning("asyncpg not available - job persistence disabled")


@dataclass
class PersistedJob:
    """Extended job data from database."""
    id: str
    model: str
    messages: list
    priority: JobPriority
    status: JobStatus
    preferred_endpoint: str | None
    assigned_endpoint: str | None
    estimated_tokens: int
    role: str | None
    created_at: datetime
    scheduled_at: datetime | None
    started_at: datetime | None
    completed_at: datetime | None
    result: str | None
    error: str | None
    input_tokens: int
    output_tokens: int
    latency_ms: int
    retry_count: int
    max_retries: int
    metadata: dict

    def to_job(self) -> Job:
        """Convert to scheduler Job object."""
        return Job(
            id=self.id,
            model=self.model,
            messages=self.messages,
            priority=self.priority,
            status=self.status,
            preferred_endpoint=self.preferred_endpoint,
            estimated_tokens=self.estimated_tokens,
            role=self.role,
            created_at=self.created_at,
            scheduled_at=self.scheduled_at,
            completed_at=self.completed_at,
            result=self.result,
            error=self.error,
        )


class JobPersistence:
    """PostgreSQL-backed job persistence layer."""

    def __init__(self, db_url: str | None = None):
        self._db_url = db_url
        self._pool: asyncpg.Pool | None = None

        if not db_url:
            self._load_db_url()

    def _load_db_url(self) -> None:
        """Load database URL from config."""
        try:
            from ..core.config import get_config
            config = get_config()
            if config._raw is not None:
                self._db_url = config._raw.get("gaius", {}).get("database", {}).get("url")
        except Exception:
            import os
            self._db_url = os.getenv("DATABASE_URL")

    async def connect(self) -> bool:
        """Connect to PostgreSQL.

        Returns:
            True if connected successfully
        """
        if not ASYNCPG_AVAILABLE:
            logger.warning("asyncpg not available, using in-memory fallback")
            return False

        if not self._db_url:
            logger.warning("No database URL configured")
            return False

        try:
            self._pool = await asyncpg.create_pool(
                self._db_url,
                min_size=2,
                max_size=10,
            )
            logger.info("Connected to PostgreSQL for job persistence")
            return True
        except Exception as e:
            logger.error(f"Failed to connect to PostgreSQL: {e}")
            return False

    async def disconnect(self) -> None:
        """Disconnect from PostgreSQL."""
        if self._pool:
            await self._pool.close()
            self._pool = None

    @property
    def connected(self) -> bool:
        """Check if connected to database."""
        return self._pool is not None

    # ─────────────────────────────────────────────────────────────────────────
    # Job Operations
    # ─────────────────────────────────────────────────────────────────────────

    async def save_job(self, job: Job) -> str:
        """Save a new job to the database.

        Args:
            job: Job to persist

        Returns:
            Job ID (may be generated if not set)
        """
        if not self._pool:
            return job.id

        async with self._pool.acquire() as conn:
            # Map priority enum to database enum
            priority_map = {
                JobPriority.CRITICAL: "critical",
                JobPriority.HIGH: "high",
                JobPriority.NORMAL: "normal",
                JobPriority.LOW: "low",
            }

            row = await conn.fetchrow(
                """
                INSERT INTO scheduler_jobs (
                    id, model, messages, priority, status,
                    preferred_endpoint, estimated_tokens, role, metadata
                ) VALUES (
                    COALESCE($1::uuid, gen_random_uuid()),
                    $2, $3::jsonb, $4::job_priority, 'pending'::job_status,
                    $5, $6, $7, $8::jsonb
                )
                RETURNING id::text
                """,
                job.id if job.id else None,
                job.model,
                json.dumps(job.messages),
                priority_map.get(job.priority, "normal"),
                job.preferred_endpoint,
                job.estimated_tokens,
                job.role,
                json.dumps({}),
            )

            job_id = row["id"]
            logger.debug(f"Saved job {job_id} to database")
            return job_id

    async def update_status(
        self,
        job_id: str,
        status: JobStatus,
        endpoint: str | None = None,
    ) -> None:
        """Update job status.

        Args:
            job_id: Job ID
            status: New status
            endpoint: Assigned endpoint (optional)
        """
        if not self._pool:
            return

        status_map = {
            JobStatus.PENDING: "pending",
            JobStatus.SCHEDULED: "scheduled",
            JobStatus.RUNNING: "running",
            JobStatus.COMPLETED: "completed",
            JobStatus.FAILED: "failed",
        }

        # Determine which timestamp to set
        timestamp_col = None
        if status == JobStatus.SCHEDULED:
            timestamp_col = "scheduled_at"
        elif status == JobStatus.RUNNING:
            timestamp_col = "started_at"
        elif status in (JobStatus.COMPLETED, JobStatus.FAILED):
            timestamp_col = "completed_at"

        async with self._pool.acquire() as conn:
            if timestamp_col:
                await conn.execute(
                    f"""
                    UPDATE scheduler_jobs
                    SET status = $1::job_status,
                        assigned_endpoint = COALESCE($2, assigned_endpoint),
                        {timestamp_col} = NOW()
                    WHERE id = $3::uuid
                    """,
                    status_map[status],
                    endpoint,
                    job_id,
                )
            else:
                await conn.execute(
                    """
                    UPDATE scheduler_jobs
                    SET status = $1::job_status,
                        assigned_endpoint = COALESCE($2, assigned_endpoint)
                    WHERE id = $3::uuid
                    """,
                    status_map[status],
                    endpoint,
                    job_id,
                )

    async def save_result(
        self,
        job_id: str,
        result: JobResult,
    ) -> None:
        """Save job result.

        Args:
            job_id: Job ID
            result: Job result
        """
        if not self._pool:
            return

        status_map = {
            JobStatus.COMPLETED: "completed",
            JobStatus.FAILED: "failed",
        }

        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE scheduler_jobs
                SET status = $1::job_status,
                    result = $2,
                    error = $3,
                    input_tokens = $4,
                    output_tokens = $5,
                    latency_ms = $6,
                    completed_at = NOW()
                WHERE id = $7::uuid
                """,
                status_map.get(result.status, "completed"),
                result.content,
                result.error,
                result.input_tokens,
                result.output_tokens,
                result.latency_ms,
                job_id,
            )

    async def get_job(self, job_id: str) -> PersistedJob | None:
        """Get a job by ID.

        Args:
            job_id: Job ID

        Returns:
            PersistedJob or None if not found
        """
        if not self._pool:
            return None

        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT
                    id::text, model, messages, priority::text, status::text,
                    preferred_endpoint, assigned_endpoint, estimated_tokens,
                    role, created_at, scheduled_at, started_at, completed_at,
                    result, error, input_tokens, output_tokens, latency_ms,
                    retry_count, max_retries, metadata
                FROM scheduler_jobs
                WHERE id = $1::uuid
                """,
                job_id,
            )

            if not row:
                return None

            return self._row_to_job(row)

    async def get_pending_jobs(self) -> list[Job]:
        """Get all pending jobs for recovery after restart.

        Returns:
            List of pending jobs
        """
        if not self._pool:
            return []

        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT
                    id::text, model, messages, priority::text, status::text,
                    preferred_endpoint, assigned_endpoint, estimated_tokens,
                    role, created_at, scheduled_at, started_at, completed_at,
                    result, error, input_tokens, output_tokens, latency_ms,
                    retry_count, max_retries, metadata
                FROM scheduler_jobs
                WHERE status IN ('pending', 'scheduled', 'running')
                ORDER BY priority, created_at
                """
            )

            return [self._row_to_job(row).to_job() for row in rows]

    async def get_failed_for_retry(self) -> list[Job]:
        """Get failed jobs that can be retried.

        Returns:
            List of jobs eligible for retry
        """
        if not self._pool:
            return []

        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT
                    id::text, model, messages, priority::text, status::text,
                    preferred_endpoint, assigned_endpoint, estimated_tokens,
                    role, created_at, scheduled_at, started_at, completed_at,
                    result, error, input_tokens, output_tokens, latency_ms,
                    retry_count, max_retries, metadata
                FROM scheduler_jobs
                WHERE status = 'failed'
                  AND retry_count < max_retries
                ORDER BY priority, created_at
                """
            )

            return [self._row_to_job(row).to_job() for row in rows]

    async def mark_for_retry(self, job_id: str) -> None:
        """Mark a failed job for retry.

        Args:
            job_id: Job ID
        """
        if not self._pool:
            return

        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE scheduler_jobs
                SET status = 'pending'::job_status,
                    retry_count = retry_count + 1,
                    scheduled_at = NULL,
                    started_at = NULL,
                    completed_at = NULL,
                    error = NULL
                WHERE id = $1::uuid
                  AND retry_count < max_retries
                """,
                job_id,
            )

    async def cleanup_old_jobs(self, days: int = 7) -> int:
        """Delete old completed jobs.

        Args:
            days: Jobs older than this many days are deleted

        Returns:
            Number of jobs deleted
        """
        if not self._pool:
            return 0

        async with self._pool.acquire() as conn:
            result = await conn.execute(
                """
                DELETE FROM scheduler_jobs
                WHERE status IN ('completed', 'failed')
                  AND completed_at < NOW() - INTERVAL '1 day' * $1
                """,
                days,
            )

            # Parse "DELETE N" response
            count = int(result.split()[-1]) if result else 0
            logger.info(f"Cleaned up {count} old jobs")
            return count

    def _row_to_job(self, row: asyncpg.Record) -> PersistedJob:
        """Convert database row to PersistedJob."""
        # Map string status to enum
        priority_map = {
            "critical": JobPriority.CRITICAL,
            "high": JobPriority.HIGH,
            "normal": JobPriority.NORMAL,
            "low": JobPriority.LOW,
        }
        status_map = {
            "pending": JobStatus.PENDING,
            "scheduled": JobStatus.SCHEDULED,
            "running": JobStatus.RUNNING,
            "completed": JobStatus.COMPLETED,
            "failed": JobStatus.FAILED,
        }

        return PersistedJob(
            id=row["id"],
            model=row["model"],
            messages=json.loads(row["messages"]) if isinstance(row["messages"], str) else row["messages"],
            priority=priority_map.get(row["priority"], JobPriority.NORMAL),
            status=status_map.get(row["status"], JobStatus.PENDING),
            preferred_endpoint=row["preferred_endpoint"],
            assigned_endpoint=row["assigned_endpoint"],
            estimated_tokens=row["estimated_tokens"] or 500,
            role=row["role"],
            created_at=row["created_at"],
            scheduled_at=row["scheduled_at"],
            started_at=row["started_at"],
            completed_at=row["completed_at"],
            result=row["result"],
            error=row["error"],
            input_tokens=row["input_tokens"] or 0,
            output_tokens=row["output_tokens"] or 0,
            latency_ms=row["latency_ms"] or 0,
            retry_count=row["retry_count"] or 0,
            max_retries=row["max_retries"] or 3,
            metadata=json.loads(row["metadata"]) if isinstance(row["metadata"], str) else (row["metadata"] or {}),
        )

    # ─────────────────────────────────────────────────────────────────────────
    # Statistics
    # ─────────────────────────────────────────────────────────────────────────

    async def get_stats(self) -> dict[str, Any]:
        """Get job statistics.

        Returns:
            Statistics dict
        """
        if not self._pool:
            return {"connected": False}

        async with self._pool.acquire() as conn:
            # Count by status
            status_counts = await conn.fetch(
                """
                SELECT status::text, COUNT(*) as count
                FROM scheduler_jobs
                GROUP BY status
                """
            )

            # Recent metrics
            recent = await conn.fetchrow(
                """
                SELECT
                    COUNT(*) as total_recent,
                    AVG(latency_ms) as avg_latency,
                    SUM(input_tokens + output_tokens) as total_tokens
                FROM scheduler_jobs
                WHERE created_at > NOW() - INTERVAL '1 hour'
                """
            )

            return {
                "connected": True,
                "by_status": {row["status"]: row["count"] for row in status_counts},
                "recent_hour": {
                    "total": recent["total_recent"] or 0,
                    "avg_latency_ms": float(recent["avg_latency"]) if recent["avg_latency"] else 0,
                    "total_tokens": recent["total_tokens"] or 0,
                },
            }


# ═══════════════════════════════════════════════════════════════════════════════
# Module-level Singleton
# ═══════════════════════════════════════════════════════════════════════════════

_persistence: JobPersistence | None = None


async def get_persistence() -> JobPersistence:
    """Get or create the job persistence singleton."""
    global _persistence
    if _persistence is None:
        _persistence = JobPersistence()
        await _persistence.connect()
    return _persistence
