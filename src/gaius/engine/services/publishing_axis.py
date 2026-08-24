"""Publishing axis: cards + arxiv/biorxiv → unique MaxSim → compact.

Guru: #SDG.00000006.STARVE
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from gaius.engine.services.axis_admit import (
    AdmitStats,
    prepare_axis_item,
    unique_maxsim,
)
from gaius.engine.services.publishing_buffer import PublishingBuffer, publishing_entry
from gaius.engine.services.sdg_aperture import SdgAperture

logger = logging.getLogger(__name__)


class PublishingAxis:
    def __init__(self, pool: Any) -> None:
        self._pool = pool
        self._buffer = PublishingBuffer(max_bytes=256 * 1024)
        self._stats = AdmitStats()
        self._task: asyncio.Task[None] | None = None
        self._summarize: Any | None = None
        self._clt: Any | None = None

    def attach_summarize(self, fn: Any) -> None:
        self._summarize = fn

    def attach_clt(self, clt: Any) -> None:
        self._clt = clt

    @property
    def buffer(self) -> PublishingBuffer:
        return self._buffer

    def stats(self) -> AdmitStats:
        return self._stats

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._roll(), name="publish-buffer-roll")

    async def _roll(self) -> None:
        while True:
            try:
                await self.ingest()
                if self._summarize is not None:
                    try:
                        out = await self._buffer.compact_if_needed(self._summarize)
                        if not out.get("skipped"):
                            logger.info(
                                "publish buffer compacted dropped=%s bytes=%s",
                                out.get("dropped"),
                                out.get("bytes"),
                            )
                    except Exception as e:
                        logger.error(
                            "publish compaction failed.\n"
                            "  Guru: #BUF.00000001.COMPACTFAIL\n"
                            "  Try: /health fix endpoints\n"
                            "  %s",
                            e,
                        )
            except Exception:
                logger.exception("publish axis roll failed")
            await asyncio.sleep(60)

    async def ingest(self) -> dict[str, Any]:
        rows = await self._load_items()
        aperture = SdgAperture.load()
        ingested = 0
        for row in rows:
            text = f"{row['title']}\n{row['body']}".strip()
            if not text:
                continue
            prepared = prepare_axis_item(
                text,
                aperture=aperture,
                stats=self._stats,
                maxsim=lambda chunk: unique_maxsim(chunk, aperture=aperture),
                clt=self._clt,
            )
            if not prepared:
                logger.warning(
                    "publish aperture starve title=%r "
                    "scanned=%s admitted=%s none=%s ambiguous=%s\n"
                    "  Guru: #SDG.00000006.STARVE",
                    row["title"][:80],
                    self._stats.scanned,
                    self._stats.admitted,
                    self._stats.none,
                    self._stats.ambiguous,
                )
                continue
            await self._buffer.add_entry(
                publishing_entry(
                    prepared["text"],
                    source=row["source"],
                    url=row.get("url") or "",
                    topic=prepared["topic"],
                    margin=prepared["margin"],
                    clt=prepared["clt"],
                )
            )
            ingested += 1
        if self._stats.starved():
            logger.warning(
                "publish axis starved scanned=%s admitted=0 none=%s ambiguous=%s\n"
                "  Guru: #SDG.00000006.STARVE (inspect for GEPA on C)",
                self._stats.scanned,
                self._stats.none,
                self._stats.ambiguous,
            )
        stats = self._buffer.get_stats()
        return {"ingested": ingested, "buffer_bytes": stats["current_bytes"]}

    async def _load_items(self) -> list[dict[str, str]]:
        out: list[dict[str, str]] = []
        async with self._pool.acquire() as conn:
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
