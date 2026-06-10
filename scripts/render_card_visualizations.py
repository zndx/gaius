#!/usr/bin/env python3
"""Render Blender visualizations for all published cards.

Generates procedural glass-structure images driven by differential geometry
and persistent homology computed on collection embedding manifolds.

Usage:
    uv run python scripts/render_card_visualizations.py [--dry-run] [--collection SLUG]
    uv run python scripts/render_card_visualizations.py --card CARD_ID  # Single card
    uv run python scripts/render_card_visualizations.py --sample 3      # UXR sample
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import time
from pathlib import Path

import asyncpg

from gaius.core.config import get_database_url

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("render-viz")


async def get_published_cards(
    pool: asyncpg.Pool,
    collection_slug: str | None = None,
) -> list[dict]:
    """Get all published cards, optionally filtered by collection."""
    if collection_slug:
        rows = await pool.fetch(
            """
            SELECT ca.card_id, ca.title, ca.image_url,
                   c.slug AS collection_slug, c.collection_id
            FROM collections.cards ca
            JOIN collections.collections c ON ca.collection_id = c.collection_id
            WHERE ca.status = 'published' AND c.slug = $1
            ORDER BY c.slug, ca.sequence NULLS LAST, ca.card_id
            """,
            collection_slug,
        )
    else:
        rows = await pool.fetch(
            """
            SELECT ca.card_id, ca.title, ca.image_url,
                   c.slug AS collection_slug, c.collection_id
            FROM collections.cards ca
            JOIN collections.collections c ON ca.collection_id = c.collection_id
            WHERE ca.status = 'published'
            ORDER BY c.slug, ca.sequence NULLS LAST, ca.card_id
            """,
        )
    return [dict(r) for r in rows]


def select_sample(cards: list[dict], n: int) -> list[dict]:
    """Select N cards stratified across collections, newest first.

    Round-robins one card from each collection, then fills remainder
    with newest cards across all collections.
    """
    from collections import defaultdict

    by_collection: dict[str, list[dict]] = defaultdict(list)
    for card in cards:
        by_collection[card["collection_slug"]].append(card)

    selected: list[dict] = []
    seen: set[str] = set()

    # Round-robin: one from each collection
    for slug in sorted(by_collection.keys()):
        if len(selected) >= n:
            break
        card = by_collection[slug][0]
        selected.append(card)
        seen.add(card["card_id"])

    # Fill remainder with remaining cards in order
    if len(selected) < n:
        for card in cards:
            if len(selected) >= n:
                break
            if card["card_id"] not in seen:
                selected.append(card)
                seen.add(card["card_id"])

    return selected


def parse_variant_arg(value: str) -> dict[str, tuple[int, int]]:
    """Parse --variants argument into a dict of variant resolutions."""
    from gaius.viz.renderer import CARD_VARIANTS

    if value == "all":
        return dict(CARD_VARIANTS)

    if value in CARD_VARIANTS:
        return {value: CARD_VARIANTS[value]}

    raise argparse.ArgumentTypeError(
        f"Unknown variant '{value}'. Choose from: {', '.join(CARD_VARIANTS.keys())}, all"
    )


async def render_single_card(
    pool: asyncpg.Pool,
    card_id: str,
    output_dir: Path,
    *,
    upload: bool = False,
    variants: dict[str, tuple[int, int]] | None = None,
) -> bool:
    """Extract features and render one card at all requested variants.

    Returns True on success, False on failure.
    """
    from gaius.viz.data import extract_card_viz_data
    from gaius.viz.renderer import CARD_VARIANTS, render_card, render_card_variants

    try:
        # Extract mathematical features
        viz_data = await extract_card_viz_data(pool, card_id)

        if variants and len(variants) > 1:
            # Multi-variant: render into card subdirectory
            card_output_dir = output_dir / card_id
            variant_paths = await render_card_variants(
                viz_data, card_output_dir, variants=variants
            )

            if upload:
                from gaius.viz.storage import (
                    update_card_image_url,
                    upload_card_variants,
                )

                urls = await upload_card_variants(card_id, variant_paths)
                # Store display variant URL in the database
                if "display" in urls:
                    await update_card_image_url(pool, card_id, urls["display"])
        else:
            # Single variant or legacy mode
            effective_variants = variants or {"display": CARD_VARIANTS["display"]}
            variant_name = next(iter(effective_variants))
            resolution = effective_variants[variant_name]

            output_path = output_dir / f"{card_id}.png"
            await render_card(viz_data, output_path, resolution=resolution)

            if upload:
                from gaius.viz.storage import update_card_image_url, upload_to_r2

                image_url = await upload_to_r2(card_id, output_path)
                await update_card_image_url(pool, card_id, image_url)

        return True
    except Exception:
        logger.exception(f"Failed to render card {card_id}")
        return False


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Show what would be done")
    parser.add_argument(
        "--collection",
        type=str,
        default=None,
        help="Only process cards from a specific collection slug",
    )
    parser.add_argument(
        "--card",
        type=str,
        default=None,
        help="Render a single card by ID",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-render cards that already have image_url",
    )
    parser.add_argument(
        "--upload",
        action="store_true",
        help="Upload to R2 and update card.image_url",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="build/viz",
        help="Output directory for rendered PNGs (default: build/viz)",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=2,
        help="Max parallel Blender renders (default: 2)",
    )
    parser.add_argument(
        "--sample",
        type=int,
        default=None,
        help="Render only N cards (stratified across collections) for UXR review",
    )
    parser.add_argument(
        "--variants",
        type=str,
        default="all",
        help="Which resolution variants to render: display, og, or all (default: all)",
    )
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    variant_dict = parse_variant_arg(args.variants)

    logger.info(
        f"Variants: {', '.join(f'{k} ({w}x{h})' for k, (w, h) in variant_dict.items())}"
    )

    db_url = get_database_url()
    pool = await asyncpg.create_pool(db_url, min_size=2, max_size=5)

    try:
        start_time = time.time()

        # Single card mode
        if args.card:
            logger.info(f"Rendering single card: {args.card}")
            success = await render_single_card(
                pool, args.card, output_dir,
                upload=args.upload, variants=variant_dict,
            )
            if success:
                logger.info(f"Done! Output: {output_dir}")
            else:
                logger.error(f"Failed to render card {args.card}")
            return

        # Batch mode
        cards = await get_published_cards(pool, args.collection)

        # Filter cards that need rendering
        if not args.force:
            needs_render = [c for c in cards if not c["image_url"]]
        else:
            needs_render = cards

        # Apply sample selection
        if args.sample is not None:
            needs_render = select_sample(needs_render, args.sample)
            logger.info(f"Sampled {len(needs_render)} cards for UXR review")

        logger.info(
            f"Cards: {len(needs_render)}/{len(cards)} to render"
            + (f" in {args.collection}" if args.collection else "")
        )

        if args.dry_run:
            for c in needs_render:
                status = "SKIP (has image)" if c["image_url"] else "RENDER"
                if args.force and c["image_url"]:
                    status = "RE-RENDER"
                logger.info(
                    f"  [{status}] {c['collection_slug']}/{c['card_id']}: "
                    f"{c['title'][:60]}"
                )
            return

        # Render with bounded concurrency
        semaphore = asyncio.Semaphore(args.concurrency)
        completed = 0
        errors = 0
        total = len(needs_render)

        async def _render_one(card: dict) -> None:
            nonlocal completed, errors
            async with semaphore:
                success = await render_single_card(
                    pool, card["card_id"], output_dir,
                    upload=args.upload, variants=variant_dict,
                )
                if success:
                    completed += 1
                else:
                    errors += 1
                logger.info(
                    f"Progress: {completed + errors}/{total} "
                    f"({completed} ok, {errors} errors)"
                )

        tasks = [_render_one(c) for c in needs_render]
        await asyncio.gather(*tasks)

        elapsed = time.time() - start_time
        logger.info(
            f"Batch complete: {completed}/{total} rendered, "
            f"{errors} errors, {elapsed:.1f}s elapsed"
        )

    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
