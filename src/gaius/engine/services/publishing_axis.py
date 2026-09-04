"""Publishing axis: cards + arxiv/biorxiv as an independent compacted FIFO.

Aperture admission is a read-time window scan, not an ingest filter.

(2026-09-04) The axis no longer rolls itself. Its 60 s ingest + thinking
compaction loop was an in-engine model workload on a private timer; the
``ambient_synthesis`` flow (pg_cron) now refreshes and compacts the
``publishing`` buffer in ``buffer_entries`` and this object is the engine's
read-through view of it. ``load_publishing_items`` is the shared query the
flow runs with its own pool.
"""

from __future__ import annotations

import logging
from typing import Any

from gaius.engine.services.ambient_buffer import BufferEntry
from gaius.engine.services.buffer_store import DurableBuffer
from gaius.engine.services.publishing_buffer import publishing_entry

logger = logging.getLogger(__name__)

PUBLISHING_BUFFER_MAX_BYTES = 256 * 1024


async def load_publishing_items(conn: Any) -> list[dict[str, str]]:
    """Newest published cards + arxiv/biorxiv items (title/body/url/source)."""
    out: list[dict[str, str]] = []
    cards = await conn.fetch(
        """
        SELECT title, COALESCE(summary, '') AS body,
               COALESCE(source_url, '') AS url
          FROM collections.cards
         WHERE status = 'published'
         ORDER BY published_at DESC NULLS LAST
         LIMIT 12
        """
    )
    papers = await conn.fetch(
        """
        SELECT c.title,
               COALESCE(c.summary, '') AS body,
               COALESCE(c.url, '') AS url
          FROM content_items c
          JOIN feed_sources s ON s.id = c.source_id
         WHERE s.source_type IN ('arxiv', 'biorxiv')
            OR s.name ILIKE '%arxiv%'
            OR s.name ILIKE '%biorxiv%'
         ORDER BY c.fetched_at DESC
         LIMIT 12
        """
    )
    for r in cards:
        out.append(
            {
                "title": str(r["title"] or ""),
                "body": str(r["body"] or ""),
                "url": str(r["url"] or ""),
                "source": "publish",
            }
        )
    for r in papers:
        out.append(
            {
                "title": str(r["title"] or ""),
                "body": str(r["body"] or ""),
                "url": str(r["url"] or ""),
                "source": "arxiv",
            }
        )
    return out


def publishing_entries(rows: list[dict[str, str]]) -> list[BufferEntry]:
    """Rows from load_publishing_items → FIFO entries (empty text skipped)."""
    out: list[BufferEntry] = []
    for row in rows:
        text = f"{row['title']}\n{row['body']}".strip()
        if not text:
            continue
        out.append(publishing_entry(text, source=row["source"], url=row.get("url") or ""))
    return out


class PublishingAxis:
    """Engine-side view of the publishing buffer (read-through cache)."""

    def __init__(self, pool: Any) -> None:
        self._pool = pool
        self._buffer = DurableBuffer(pool, "publishing", PUBLISHING_BUFFER_MAX_BYTES)
        self._clt: Any | None = None

    def attach_clt(self, clt: Any) -> None:
        self._clt = clt

    @property
    def buffer(self) -> DurableBuffer:
        return self._buffer

    def start(self) -> None:
        """Keep the cached stats current. No ingest, no model work here."""
        self._buffer.start_refresh()

    async def stop(self) -> None:
        await self._buffer.stop_refresh()
