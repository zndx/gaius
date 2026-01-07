"""Content processing pipeline.

Processes fetched content items and writes them to the KB.
Optionally generates embeddings for Qdrant.

Pipeline:
1. Select unprocessed content items (processed_at IS NULL)
2. Generate markdown for each item
3. Write to KB path (build/dev/current/content/<source>/)
4. Update content_items.kb_path and processed_at
"""

import asyncio
import logging
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from gaius.workers.config import WorkerConfig
from gaius.workers.db import Database
from gaius.workers.models import ContentItem

logger = logging.getLogger(__name__)

# KB root directory
KB_ROOT = Path(os.getenv("GAIUS_KB_ROOT", "build/dev"))


class ContentProcessor:
    """Processes content items into KB entries."""

    def __init__(self, config: WorkerConfig, db: Database):
        self.config = config
        self.db = db
        self.kb_root = KB_ROOT if KB_ROOT.is_absolute() else Path.cwd() / KB_ROOT

    async def process_batch(self, limit: int = 50) -> int:
        """Process a batch of unprocessed content items.

        Returns the number of items processed.
        """
        items = await self._get_unprocessed_items(limit)
        if not items:
            return 0

        processed = 0
        for item in items:
            try:
                kb_path = await self._process_item(item)
                if kb_path and item.id is not None:
                    await self._mark_processed(item.id, kb_path)
                    processed += 1
            except Exception as e:
                logger.error(f"Error processing item {item.id}: {e}")

        return processed

    async def _get_unprocessed_items(self, limit: int) -> list[ContentItem]:
        """Get unprocessed content items with source name."""
        rows = await self.db.pool.fetch(
            """
            SELECT ci.*, fs.name as source_name
            FROM content_items ci
            JOIN feed_sources fs ON ci.source_id = fs.id
            WHERE ci.processed_at IS NULL
            ORDER BY ci.fetched_at DESC
            LIMIT $1
            """,
            limit,
        )
        items = []
        for row in rows:
            row_dict = dict(row)
            source_name = row_dict.pop("source_name", None)
            item = ContentItem.from_row(row_dict)
            # Add source_name to metadata for path generation
            item.metadata["source_name"] = source_name
            items.append(item)
        return items

    async def _process_item(self, item: ContentItem) -> str | None:
        """Process a single item and return its KB path."""
        # Determine KB path
        source_name = item.metadata.get("source_name", f"source_{item.source_id}")
        safe_title = self._safe_filename(item.title)
        date_str = datetime.now().strftime("%Y-%m-%d")

        kb_path = f"current/content/{source_name}/{date_str}/{safe_title}.md"
        full_path = self.kb_root / kb_path

        # Create directory
        full_path.parent.mkdir(parents=True, exist_ok=True)

        # Generate markdown content
        content = self._generate_markdown(item)

        # Write file
        full_path.write_text(content)
        logger.info(f"Wrote KB entry: {kb_path}")

        return kb_path

    async def _mark_processed(self, item_id: int, kb_path: str) -> None:
        """Mark an item as processed."""
        await self.db.pool.execute(
            """
            UPDATE content_items
            SET processed_at = NOW(), kb_path = $2
            WHERE id = $1
            """,
            item_id,
            kb_path,
        )

    def _generate_markdown(self, item: ContentItem) -> str:
        """Generate markdown content for an item."""
        lines = [
            f"# {item.title}",
            "",
        ]

        # Metadata block
        lines.append("---")
        if item.url:
            lines.append(f"url: {item.url}")
        if item.authors:
            lines.append(f"authors: {', '.join(item.authors)}")
        if item.published_at:
            lines.append(f"published: {item.published_at.isoformat()}")
        if item.external_id:
            lines.append(f"external_id: {item.external_id}")
        lines.append(f"fetched: {item.fetched_at.isoformat() if item.fetched_at else 'unknown'}")
        lines.append("---")
        lines.append("")

        # Summary
        if item.summary:
            lines.append("## Summary")
            lines.append("")
            lines.append(item.summary)
            lines.append("")

        # Content
        if item.content:
            lines.append("## Content")
            lines.append("")
            lines.append(item.content)
            lines.append("")

        # Metadata
        if item.metadata:
            lines.append("## Metadata")
            lines.append("")
            lines.append("```json")
            import json
            lines.append(json.dumps(item.metadata, indent=2, default=str))
            lines.append("```")

        return "\n".join(lines)

    def _safe_filename(self, title: str) -> str:
        """Convert title to safe filename."""
        # Remove/replace unsafe characters
        safe = re.sub(r'[^\w\s-]', '', title.lower())
        safe = re.sub(r'[-\s]+', '-', safe)
        # Truncate to reasonable length
        return safe[:80].strip('-')


async def process_content(config: WorkerConfig, limit: int = 50) -> int:
    """Process content items to KB.

    Returns the number of items processed.
    """
    db = await Database.connect(
        config.db_url,
        min_size=1,
        max_size=2,
    )
    try:
        processor = ContentProcessor(config, db)
        return await processor.process_batch(limit)
    finally:
        await db.close()
