"""Database operations for fetch workers.

Uses asyncpg for high-performance async PostgreSQL access.
Job claiming uses SELECT FOR UPDATE SKIP LOCKED for safe concurrency.
"""

import asyncio
import json
from datetime import datetime
from typing import Any

import asyncpg

from gaius.workers.models import (
    ContentItem,
    FeedSource,
    FetchJob,
    JobStatus,
    SourceType,
)


class Database:
    """Async database connection pool and operations."""

    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    @classmethod
    async def connect(cls, db_url: str, min_size: int = 2, max_size: int = 10) -> "Database":
        """Create a database connection pool."""
        pool = await asyncpg.create_pool(
            db_url,
            min_size=min_size,
            max_size=max_size,
            # Custom type codecs for JSONB
            init=_init_connection,
        )
        return cls(pool)

    async def close(self) -> None:
        """Close the connection pool."""
        await self.pool.close()

    # -------------------------------------------------------------------------
    # Job Operations
    # -------------------------------------------------------------------------

    async def claim_next_job(self, timeout_seconds: int = 300) -> FetchJob | None:
        """Claim the next scheduled job atomically.

        Uses SELECT FOR UPDATE SKIP LOCKED to prevent race conditions.
        Also auto-fails jobs that have been running too long.
        """
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                # First, fail any timed-out jobs
                await conn.execute(
                    """
                    UPDATE fetch_jobs
                    SET status = 'failed',
                        completed_at = NOW(),
                        error_message = 'Job timed out'
                    WHERE status = 'running'
                      AND started_at < NOW() - ($1 || ' seconds')::INTERVAL
                    """,
                    str(timeout_seconds),
                )

                # Claim next scheduled job
                row = await conn.fetchrow(
                    """
                    UPDATE fetch_jobs
                    SET status = 'running', started_at = NOW()
                    WHERE id = (
                        SELECT id FROM fetch_jobs
                        WHERE status = 'scheduled'
                        ORDER BY id
                        FOR UPDATE SKIP LOCKED
                        LIMIT 1
                    )
                    RETURNING *
                    """
                )

                if row is None:
                    return None

                job = FetchJob.from_row(dict(row))

                # Load the associated source
                source_row = await conn.fetchrow(
                    "SELECT * FROM feed_sources WHERE id = $1",
                    job.source_id,
                )
                if source_row:
                    job.source = FeedSource.from_row(dict(source_row))

                return job

    async def complete_job(
        self,
        job_id: int,
        items_fetched: int,
        items_new: int,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Mark a job as successfully completed."""
        await self.pool.execute(
            """
            UPDATE fetch_jobs
            SET status = 'success',
                completed_at = NOW(),
                items_fetched = $2,
                items_new = $3,
                metadata = COALESCE($4, metadata)
            WHERE id = $1
            """,
            job_id,
            items_fetched,
            items_new,
            metadata,  # asyncpg JSONB codec handles serialization
        )

    async def fail_job(
        self,
        job_id: int,
        error_message: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Mark a job as failed."""
        await self.pool.execute(
            """
            UPDATE fetch_jobs
            SET status = 'failed',
                completed_at = NOW(),
                error_message = $2,
                metadata = COALESCE($3, metadata)
            WHERE id = $1
            """,
            job_id,
            error_message,
            metadata,  # asyncpg JSONB codec handles serialization
        )

    async def get_job(self, job_id: int) -> FetchJob | None:
        """Get a job by ID."""
        row = await self.pool.fetchrow(
            "SELECT * FROM fetch_jobs WHERE id = $1",
            job_id,
        )
        return FetchJob.from_row(dict(row)) if row else None

    # -------------------------------------------------------------------------
    # Source Operations
    # -------------------------------------------------------------------------

    async def get_source(self, source_id: int) -> FeedSource | None:
        """Get a source by ID."""
        row = await self.pool.fetchrow(
            "SELECT * FROM feed_sources WHERE id = $1",
            source_id,
        )
        return FeedSource.from_row(dict(row)) if row else None

    async def get_source_by_name(self, name: str) -> FeedSource | None:
        """Get a source by name."""
        row = await self.pool.fetchrow(
            "SELECT * FROM feed_sources WHERE name = $1",
            name,
        )
        return FeedSource.from_row(dict(row)) if row else None

    async def update_source_last_fetch(self, source_id: int) -> None:
        """Update the last_fetch_at timestamp for a source."""
        await self.pool.execute(
            "UPDATE feed_sources SET last_fetch_at = NOW() WHERE id = $1",
            source_id,
        )

    async def list_active_sources(self) -> list[FeedSource]:
        """List all active feed sources."""
        rows = await self.pool.fetch(
            "SELECT * FROM feed_sources WHERE active = true ORDER BY name"
        )
        return [FeedSource.from_row(dict(row)) for row in rows]

    # -------------------------------------------------------------------------
    # Content Operations
    # -------------------------------------------------------------------------

    async def insert_content_item(
        self,
        item: ContentItem,
        iceberg_id: str | None = None,
        iceberg_snapshot_id: int | None = None,
    ) -> int:
        """Insert a content item metadata, returning its ID.

        Raw content is stored in Iceberg (HX), not PostgreSQL.
        Only metadata (title, authors, URLs, timestamps) goes to PostgreSQL.

        Args:
            item: ContentItem with metadata.
            iceberg_id: UUID of the content in Iceberg raw.content table.
            iceberg_snapshot_id: Iceberg snapshot ID for time-travel queries.

        Returns:
            PostgreSQL content_items.id
        """
        row = await self.pool.fetchrow(
            """
            INSERT INTO content_items (
                source_id, external_id, url, title, authors,
                summary, content_type, metadata,
                published_at, fetched_at,
                iceberg_id, iceberg_snapshot_id
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, NOW(), $10, $11)
            ON CONFLICT (source_id, external_id) DO UPDATE
            SET title = EXCLUDED.title,
                authors = EXCLUDED.authors,
                summary = EXCLUDED.summary,
                metadata = EXCLUDED.metadata,
                fetched_at = NOW(),
                iceberg_id = COALESCE(EXCLUDED.iceberg_id, content_items.iceberg_id),
                iceberg_snapshot_id = COALESCE(EXCLUDED.iceberg_snapshot_id, content_items.iceberg_snapshot_id)
            RETURNING id
            """,
            item.source_id,
            item.external_id,
            item.url,
            item.title,
            item.authors,
            item.summary,
            item.content_type,
            item.metadata,  # asyncpg JSONB codec handles serialization
            item.published_at,
            iceberg_id,
            iceberg_snapshot_id,
        )
        return row["id"]

    async def insert_content_items(
        self,
        items: list[ContentItem],
        iceberg_ids: dict[str, str] | None = None,
        iceberg_snapshot_id: int | None = None,
    ) -> tuple[int, int, list[ContentItem]]:
        """Insert multiple content items metadata.

        Raw content goes to Iceberg (HX), metadata goes to PostgreSQL.

        Args:
            items: ContentItem objects with metadata.
            iceberg_ids: Map of external_id -> iceberg_id (UUID in Iceberg).
            iceberg_snapshot_id: Iceberg snapshot ID for all items in batch.

        Returns:
            Tuple of (total_inserted, new_count, new_items).
            new_items contains only items that were newly inserted (for HX write).
        """
        total = 0
        new_count = 0
        new_items: list[ContentItem] = []

        iceberg_ids = iceberg_ids or {}

        for item in items:
            # Check if exists
            existing = await self.pool.fetchval(
                """
                SELECT id FROM content_items
                WHERE source_id = $1 AND external_id = $2
                """,
                item.source_id,
                item.external_id,
            )

            # Get iceberg_id for this item if available
            iceberg_id = iceberg_ids.get(item.external_id or "")

            item_id = await self.insert_content_item(
                item,
                iceberg_id=iceberg_id,
                iceberg_snapshot_id=iceberg_snapshot_id,
            )
            total += 1
            if existing is None:
                new_count += 1
                new_items.append(item)

        return total, new_count, new_items

    async def get_content_by_external_id(
        self, source_id: int, external_id: str
    ) -> ContentItem | None:
        """Get a content item by source and external ID."""
        row = await self.pool.fetchrow(
            """
            SELECT * FROM content_items
            WHERE source_id = $1 AND external_id = $2
            """,
            source_id,
            external_id,
        )
        return ContentItem.from_row(dict(row)) if row else None

    async def content_exists(self, source_id: int, external_id: str) -> bool:
        """Check if content item already exists."""
        result = await self.pool.fetchval(
            """
            SELECT EXISTS(
                SELECT 1 FROM content_items
                WHERE source_id = $1 AND external_id = $2
            )
            """,
            source_id,
            external_id,
        )
        return result

    # -------------------------------------------------------------------------
    # Stats and Monitoring
    # -------------------------------------------------------------------------

    async def get_pending_job_count(self) -> int:
        """Get count of scheduled (pending) jobs."""
        return await self.pool.fetchval(
            "SELECT COUNT(*) FROM fetch_jobs WHERE status = 'scheduled'"
        )

    async def get_source_stats(self) -> list[dict[str, Any]]:
        """Get stats for all sources."""
        rows = await self.pool.fetch(
            """
            SELECT * FROM v_source_status
            """
        )
        return [dict(row) for row in rows]


async def _init_connection(conn: asyncpg.Connection) -> None:
    """Initialize connection with custom type codecs."""
    # Register JSONB codec
    await conn.set_type_codec(
        "jsonb",
        encoder=json.dumps,
        decoder=json.loads,
        schema="pg_catalog",
    )
    # Also for json type
    await conn.set_type_codec(
        "json",
        encoder=json.dumps,
        decoder=json.loads,
        schema="pg_catalog",
    )
