"""Backfill source files and provenance records for existing cards.

One-time migration script to bring ai-reasoning-agents collection into
full compliance: every card gets a source file on disk, a Source record
in Postgres, and updated metadata (zettle_slug, kb_path).

Usage:
    uv run python scripts/backfill_sources.py
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from pathlib import Path

import asyncpg
import yaml

from gaius.core.config import get_database_url


ZETTLE_SLUG = "ai-reasoning-agents"
KB_ROOT = Path("build/dev")
SOURCES_DIR = KB_ROOT / "current" / "articles" / ZETTLE_SLUG / "sources"


def generate_source_id() -> str:
    """Generate a unique source_id like ref_xxxxxxxxxxxx."""
    return f"ref_{uuid.uuid4().hex[:12]}"


def create_source_markdown(card: dict) -> str:
    """Create an AcquiredSource-compatible markdown file for a card."""
    frontmatter = {
        "source_id": card["source_id"],
        "source_type": card["source_type"],
        "url": card["source_url"],
        "title": card["title"],
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }

    body = f"# {card['title']}\n\n"
    body += f"Source: {card['source_url']}\n"
    body += f"Type: {card['source_type']}\n\n"
    body += f"## Summary\n{card['summary']}\n"

    return f"---\n{yaml.dump(frontmatter, default_flow_style=False)}---\n\n{body}"


async def backfill() -> None:
    """Run the backfill."""
    db_url = get_database_url()
    pool = await asyncpg.create_pool(db_url, min_size=1, max_size=3)

    try:
        async with pool.acquire() as conn:
            # Get the featured collection
            collection = await conn.fetchrow(
                "SELECT * FROM collections.collections WHERE featured = TRUE LIMIT 1"
            )
            if not collection:
                raise RuntimeError("No featured collection found")

            collection_id = collection["collection_id"]
            print(f"Collection: {collection_id} ({collection['slug']})")

            # Get all cards
            cards = await conn.fetch(
                """
                SELECT card_id, title, summary, source_url, source_type, status
                FROM collections.cards
                WHERE collection_id = $1
                ORDER BY created_at
                """,
                collection_id,
            )
            print(f"Found {len(cards)} cards")

            # Ensure sources directory exists
            SOURCES_DIR.mkdir(parents=True, exist_ok=True)

            for card in cards:
                card_dict = dict(card)
                source_id = generate_source_id()
                card_dict["source_id"] = source_id

                # 1. Create source file on disk
                source_file = SOURCES_DIR / f"{source_id}.md"
                source_file.write_text(create_source_markdown(card_dict))
                print(f"  Created: {source_file.name}")

                # 2. Build KB path (relative to KB root)
                kb_path = f"current/articles/{ZETTLE_SLUG}/sources/{source_id}.md"

                # 3. Update card metadata
                await conn.execute(
                    """
                    UPDATE collections.cards
                    SET zettle_slug = $2,
                        kb_path = $3
                    WHERE card_id = $1
                    """,
                    card_dict["card_id"],
                    ZETTLE_SLUG,
                    kb_path,
                )

                # 4. Insert source record
                await conn.execute(
                    """
                    INSERT INTO collections.sources
                    (source_id, card_id, provenance_url, source_type,
                     ingested_via, kb_path, ingested_at)
                    VALUES ($1, $2, $3, $4, $5, $6, NOW())
                    ON CONFLICT (source_id) DO NOTHING
                    """,
                    source_id,
                    card_dict["card_id"],
                    card_dict["source_url"],
                    card_dict["source_type"],
                    "backfill",
                    kb_path,
                )

            # 5. Update article sources_count
            await conn.execute(
                """
                UPDATE collections.articles
                SET sources_count = (
                    SELECT COUNT(DISTINCT s.source_id)
                    FROM collections.sources s
                    JOIN collections.cards c ON c.card_id = s.card_id
                    WHERE c.collection_id = $1
                ),
                updated_at = NOW()
                WHERE collection_id = $1
                """,
                collection_id,
            )

            # Verify
            source_count = await conn.fetchval(
                "SELECT COUNT(*) FROM collections.sources"
            )
            card_with_slug = await conn.fetchval(
                "SELECT COUNT(*) FROM collections.cards WHERE zettle_slug IS NOT NULL AND collection_id = $1",
                collection_id,
            )
            article_sources = await conn.fetchval(
                "SELECT sources_count FROM collections.articles WHERE collection_id = $1",
                collection_id,
            )
            disk_files = len(list(SOURCES_DIR.glob("*.md")))

            print(f"\n--- Verification ---")
            print(f"Source records in Postgres: {source_count}")
            print(f"Cards with zettle_slug:    {card_with_slug}")
            print(f"Article sources_count:     {article_sources}")
            print(f"Source files on disk:       {disk_files}")

            if source_count == len(cards) and card_with_slug == len(cards) and disk_files == len(cards):
                print("\nBackfill complete — all stores in sync.")
            else:
                print(f"\nWARNING: Expected {len(cards)} everywhere, check discrepancies.")

    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(backfill())
