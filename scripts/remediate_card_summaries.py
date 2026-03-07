#!/usr/bin/env python3
"""Remediate card summaries for ai-keiretsu and cyber-physical-systems.

Generates frontier (Brave Answers), open_weights (local GPU), and cerebras
(GLM-4.7 thinking) summaries for all published cards missing any summary type,
then syncs to KV.

Usage:
    uv run python scripts/remediate_card_summaries.py [--dry-run] [--collection SLUG]
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import time

import asyncpg

from gaius.core.config import get_database_url

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("remediate")

TARGET_COLLECTIONS = ("ai-keiretsu", "cyber-physical-systems", "ai-reasoning-agents", "gaius-content-curation")


async def get_cards_needing_summaries(
    pool: asyncpg.Pool,
    slugs: tuple[str, ...],
) -> list[dict]:
    """Get published cards that are missing one or more summary types."""
    rows = await pool.fetch(
        """
        SELECT
            ca.card_id,
            ca.title,
            c.slug AS collection_slug,
            c.collection_id,
            (SELECT COUNT(*) FROM collections.card_summaries cs
             WHERE cs.card_id = ca.card_id AND cs.summary_type = 'frontier') AS has_frontier,
            (SELECT COUNT(*) FROM collections.card_summaries cs
             WHERE cs.card_id = ca.card_id AND cs.summary_type = 'open_weights') AS has_open_weights,
            (SELECT COUNT(*) FROM collections.card_summaries cs
             WHERE cs.card_id = ca.card_id AND cs.summary_type = 'cerebras') AS has_cerebras
        FROM collections.cards ca
        JOIN collections.collections c ON ca.collection_id = c.collection_id
        WHERE ca.status = 'published'
          AND c.slug = ANY($1::text[])
        ORDER BY c.slug, ca.card_id
        """,
        list(slugs),
    )
    return [dict(r) for r in rows]


async def get_collections_needing_summaries(
    pool: asyncpg.Pool,
    slugs: tuple[str, ...],
) -> list[dict]:
    """Get collections missing one or more summary types."""
    rows = await pool.fetch(
        """
        SELECT
            c.collection_id,
            c.slug,
            c.name,
            (SELECT COUNT(*) FROM collections.collection_summaries cs
             WHERE cs.collection_id = c.collection_id AND cs.summary_type = 'frontier') AS has_frontier,
            (SELECT COUNT(*) FROM collections.collection_summaries cs
             WHERE cs.collection_id = c.collection_id AND cs.summary_type = 'open_weights') AS has_open_weights,
            (SELECT COUNT(*) FROM collections.collection_summaries cs
             WHERE cs.collection_id = c.collection_id AND cs.summary_type = 'cerebras') AS has_cerebras
        FROM collections.collections c
        WHERE c.slug = ANY($1::text[])
        ORDER BY c.slug
        """,
        list(slugs),
    )
    return [dict(r) for r in rows]


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Show what would be done")
    parser.add_argument(
        "--collection",
        type=str,
        default=None,
        help="Only process a specific collection slug",
    )
    parser.add_argument(
        "--skip-card-summaries",
        action="store_true",
        help="Skip card summary generation (do collection summaries + KV sync only)",
    )
    parser.add_argument(
        "--skip-collection-summaries",
        action="store_true",
        help="Skip collection summary generation",
    )
    parser.add_argument(
        "--skip-kv-sync",
        action="store_true",
        help="Skip KV sync (DB-only)",
    )
    args = parser.parse_args()

    slugs = (args.collection,) if args.collection else TARGET_COLLECTIONS

    db_url = get_database_url()
    pool = await asyncpg.create_pool(db_url, min_size=2, max_size=5)

    try:
        # ===================================================================
        # Step 1: Card Summaries
        # ===================================================================
        if not args.skip_card_summaries:
            cards = await get_cards_needing_summaries(pool, slugs)
            needs_work = [
                c for c in cards
                if c["has_frontier"] == 0 or c["has_open_weights"] == 0 or c["has_cerebras"] == 0
            ]
            logger.info(
                f"Card summaries: {len(needs_work)}/{len(cards)} cards need work "
                f"across {', '.join(slugs)}"
            )

            if args.dry_run:
                for c in needs_work:
                    missing = []
                    if c["has_frontier"] == 0:
                        missing.append("frontier")
                    if c["has_open_weights"] == 0:
                        missing.append("open_weights")
                    if c["has_cerebras"] == 0:
                        missing.append("cerebras")
                    logger.info(
                        f"  [DRY-RUN] {c['collection_slug']}/{c['card_id']}: "
                        f"{c['title'][:60]} — missing {', '.join(missing)}"
                    )
            else:
                from gaius.engine.services.collection_service import (
                    CollectionService,
                )

                svc = CollectionService(pool)
                total = len(needs_work)
                completed = 0
                errors = 0

                for card in needs_work:
                    card_id = card["card_id"]
                    title_short = card["title"][:50]

                    # Generate frontier if missing
                    if card["has_frontier"] == 0:
                        try:
                            t0 = time.monotonic()
                            result = await svc.generate_card_summary(
                                card_id, summary_type="frontier"
                            )
                            elapsed = time.monotonic() - t0
                            logger.info(
                                f"  [{completed+1}/{total}] frontier OK: "
                                f"{title_short} ({elapsed:.1f}s, "
                                f"{result.get('output_tokens', '?')} tokens)"
                            )
                        except Exception as e:
                            errors += 1
                            logger.error(
                                f"  [{completed+1}/{total}] frontier FAIL: "
                                f"{title_short}: {e}"
                            )

                    # Generate open_weights if missing
                    if card["has_open_weights"] == 0:
                        try:
                            t0 = time.monotonic()
                            result = await svc.generate_card_summary(
                                card_id, summary_type="open_weights"
                            )
                            elapsed = time.monotonic() - t0
                            logger.info(
                                f"  [{completed+1}/{total}] open_weights OK: "
                                f"{title_short} ({elapsed:.1f}s, "
                                f"{result.get('output_tokens', '?')} tokens)"
                            )
                        except Exception as e:
                            errors += 1
                            logger.error(
                                f"  [{completed+1}/{total}] open_weights FAIL: "
                                f"{title_short}: {e}"
                            )

                    # Generate cerebras if missing
                    if card["has_cerebras"] == 0:
                        try:
                            t0 = time.monotonic()
                            result = await svc.generate_card_summary(
                                card_id, summary_type="cerebras"
                            )
                            elapsed = time.monotonic() - t0
                            logger.info(
                                f"  [{completed+1}/{total}] cerebras OK: "
                                f"{title_short} ({elapsed:.1f}s, "
                                f"{result.get('output_tokens', '?')} tokens)"
                            )
                        except Exception as e:
                            errors += 1
                            logger.error(
                                f"  [{completed+1}/{total}] cerebras FAIL: "
                                f"{title_short}: {e}"
                            )

                    # Sync card to KV
                    if not args.skip_kv_sync:
                        try:
                            await svc.sync_card_to_kv(card_id)
                            logger.info(f"  [{completed+1}/{total}] KV sync OK: {title_short}")
                        except Exception as e:
                            errors += 1
                            logger.error(
                                f"  [{completed+1}/{total}] KV sync FAIL: "
                                f"{title_short}: {e}"
                            )

                    completed += 1

                logger.info(
                    f"Card summaries complete: {completed}/{total} processed, "
                    f"{errors} errors"
                )

        # ===================================================================
        # Step 2: Collection Summaries
        # ===================================================================
        if not args.skip_collection_summaries:
            collections = await get_collections_needing_summaries(pool, slugs)
            needs_work = [
                c for c in collections
                if c["has_frontier"] == 0 or c["has_open_weights"] == 0 or c["has_cerebras"] == 0
            ]
            logger.info(
                f"Collection summaries: {len(needs_work)}/{len(collections)} "
                f"collections need work"
            )

            if args.dry_run:
                for c in needs_work:
                    missing = []
                    if c["has_frontier"] == 0:
                        missing.append("frontier")
                    if c["has_open_weights"] == 0:
                        missing.append("open_weights")
                    if c["has_cerebras"] == 0:
                        missing.append("cerebras")
                    logger.info(
                        f"  [DRY-RUN] {c['slug']}: {c['name']} — "
                        f"missing {', '.join(missing)}"
                    )
            else:
                from gaius.engine.services.collection_service import (
                    CollectionService,
                )

                svc = CollectionService(pool)

                for coll in needs_work:
                    cid = coll["collection_id"]
                    slug = coll["slug"]

                    if coll["has_frontier"] == 0:
                        try:
                            t0 = time.monotonic()
                            result = await svc.generate_collection_summary(
                                cid, summary_type="frontier"
                            )
                            elapsed = time.monotonic() - t0
                            logger.info(
                                f"  collection frontier OK: {slug} ({elapsed:.1f}s)"
                            )
                        except Exception as e:
                            logger.error(
                                f"  collection frontier FAIL: {slug}: {e}"
                            )

                    if coll["has_open_weights"] == 0:
                        try:
                            t0 = time.monotonic()
                            result = await svc.generate_collection_summary(
                                cid, summary_type="open_weights"
                            )
                            elapsed = time.monotonic() - t0
                            logger.info(
                                f"  collection open_weights OK: {slug} ({elapsed:.1f}s)"
                            )
                        except Exception as e:
                            logger.error(
                                f"  collection open_weights FAIL: {slug}: {e}"
                            )

                    if coll.get("has_cerebras", 0) == 0:
                        try:
                            t0 = time.monotonic()
                            result = await svc.generate_collection_summary(
                                cid, summary_type="cerebras"
                            )
                            elapsed = time.monotonic() - t0
                            logger.info(
                                f"  collection cerebras OK: {slug} ({elapsed:.1f}s)"
                            )
                        except Exception as e:
                            logger.error(
                                f"  collection cerebras FAIL: {slug}: {e}"
                            )

        # ===================================================================
        # Step 3: KV Sync (landing, collections index, per-collection)
        # ===================================================================
        if not args.skip_kv_sync and not args.dry_run:
            from gaius.engine.services.collection_service import (
                CollectionService,
            )

            svc = CollectionService(pool)

            # 3a. Sync published_cards (landing page) — all published cards
            logger.info("Syncing published_cards KV (landing page)...")
            try:
                result = await svc.sync_to_kv()
                logger.info(
                    f"  published_cards KV: {result.get('cards_synced', '?')} cards synced"
                )
            except Exception as e:
                logger.error(f"  published_cards KV FAIL: {e}")

            # 3b. Sync collections index
            logger.info("Syncing collections_index KV...")
            try:
                result = await svc.sync_collections_index_to_kv()
                logger.info(
                    f"  collections_index KV: "
                    f"{result.get('collections_synced', '?')} collections synced"
                )
            except Exception as e:
                logger.error(f"  collections_index KV FAIL: {e}")

            # 3c. Sync each collection's page data
            all_collections = await pool.fetch(
                """
                SELECT collection_id, slug
                FROM collections.collections
                WHERE status = 'active'
                ORDER BY slug
                """
            )
            for row in all_collections:
                logger.info(f"Syncing collection KV: {row['slug']}...")
                try:
                    result = await svc.sync_collection_to_kv(row["collection_id"])
                    logger.info(
                        f"  collection KV: {row['slug']} — "
                        f"{result.get('cards_synced', '?')} cards, "
                        f"{result.get('aliases_synced', '?')} aliases"
                    )
                except Exception as e:
                    logger.error(f"  collection KV FAIL: {row['slug']}: {e}")

        # ===================================================================
        # Final verification
        # ===================================================================
        logger.info("--- Verification ---")

        # Card summaries
        rows = await pool.fetch(
            """
            SELECT c.slug, cs.summary_type, COUNT(*) as cnt
            FROM collections.card_summaries cs
            JOIN collections.cards ca ON ca.card_id = cs.card_id
            JOIN collections.collections c ON c.collection_id = ca.collection_id
            GROUP BY c.slug, cs.summary_type
            ORDER BY c.slug, cs.summary_type
            """
        )
        for r in rows:
            logger.info(f"  card_summaries: {r['slug']}/{r['summary_type']} = {r['cnt']}")

        # Collection summaries
        rows = await pool.fetch(
            """
            SELECT c.slug, cs.summary_type
            FROM collections.collection_summaries cs
            JOIN collections.collections c ON c.collection_id = cs.collection_id
            ORDER BY c.slug, cs.summary_type
            """
        )
        for r in rows:
            logger.info(f"  collection_summaries: {r['slug']}/{r['summary_type']}")

    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
