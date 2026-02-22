"""CardUpkeepFlow - Publish cards from article .base files to Cloudflare KV.

This flow implements a 7-step pipeline with parallel article processing:
1. start: Scan .base files for references needing cards
2. process_article: Create cards per article (foreach parallel)
3. join_articles: Merge parallel results
4. publish_batch: Publish pending cards
5. sync_to_kv: Push to Cloudflare KV
6. update_base_files: Update card_status in .base files
7. end: Emit lineage, report summary

FAIL-FAST: This flow fails immediately if required services are unavailable.
No fallbacks or placeholder content is generated.

Guru Meditation Codes:
- #CUF.00000001.NOBASE: No .base files found with eligible references
- #CUF.00000002.ARTICLEFAIL: Article processing failed
- #CUF.00000003.CARDCREATE: Card creation failed
- #CUF.00000004.PUBLISHFAIL: Card publish failed
- #CUF.00000005.KVSYNCFAIL: Cloudflare KV sync failed
- #CUF.00000006.BASEUPDATE: Base file update failed
- #CUF.00000007.NOFEATURED: No featured collection configured

Usage:
    # Via Metaflow CLI
    python -m gaius.flows.card_upkeep.flow run

    # Process specific article
    python -m gaius.flows.card_upkeep.flow run --article ai-keiretsu

    # Dry run
    python -m gaius.flows.card_upkeep.flow run --dry_run True
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from metaflow import Parameter, step

from gaius.agents.metaagent.telemetry import TracedFlow, traced_step
from gaius.flows import register_flow
from gaius.flows.base import GaiusFlow
from gaius.flows.article_curation.common import CardStatus
from gaius.flows.card_upkeep.common import (
    ArticleProcessResult,
    extract_source_type,
    parse_base_file,
    scan_base_files,
    traceable_id_to_url,
    update_base_file,
)
from gaius.hx.lineage.events import Dataset

logger = logging.getLogger(__name__)


def _get_database_url() -> str:
    """Get database URL for asyncpg pool."""
    from gaius.core.config import get_database_url
    return get_database_url()


def _extract_title(content: str) -> str:
    """Extract title from card content.

    Uses first line if it's a heading, otherwise first 80 chars.

    Args:
        content: Card content (passage from extracted text)

    Returns:
        Title string (max 80 chars)
    """
    if not content:
        return ""

    # Split on newlines, get first non-empty line
    lines = content.strip().split("\n")
    first_line = ""
    for line in lines:
        line = line.strip()
        if line:
            first_line = line
            break

    if not first_line:
        return ""

    # Strip markdown heading markers
    if first_line.startswith("#"):
        first_line = first_line.lstrip("#").strip()

    # Truncate to 80 chars
    if len(first_line) > 80:
        return first_line[:77] + "..."

    return first_line


@register_flow("card_upkeep")
class CardUpkeepFlow(TracedFlow, GaiusFlow):
    """Publish cards from article .base files to Cloudflare KV.

    Uses foreach pattern for parallel article processing with
    per-article error isolation.

    OTel Integration:
        - Inherits from TracedFlow for automatic span creation
        - Emits semantic events for key operations
        - Success metrics for longitudinal health diagnostics
    """

    article_slug = Parameter(
        "article",
        help="Specific article slug to process (default: all eligible)",
        default=None,
        required=False,
    )

    max_articles = Parameter(
        "max_articles",
        help="Maximum articles to process in batch",
        default=3,
        type=int,
    )

    publish_count = Parameter(
        "publish_count",
        help="Number of cards to publish from pending queue",
        default=3,
        type=int,
    )

    dry_run = Parameter(
        "dry_run",
        help="Dry run - don't modify .base files or publish to KV",
        default=False,
        type=bool,
    )

    @traced_step
    @step
    def start(self):
        """Scan .base files for references needing cards."""
        print("Scanning for .base files with eligible references...")

        # Emit lineage START
        self.emit_lineage_start(
            job_name="card_upkeep",
            inputs=[Dataset.from_source("kb", "articles")],
        )

        # Scan for eligible .base files
        eligible = scan_base_files(
            kb_root=self.kb_root,
            article_slug=self.article_slug,
            max_articles=self.max_articles,
        )

        if not eligible:
            # Not a failure - just nothing to do
            print("No .base files found with eligible references (unknown/pending)")
            self.article_paths = []
            self.next(self.end)
            return

        # Store paths for foreach
        self.article_paths = [str(base_path) for base_path, _ in eligible]
        self.eligible_count = sum(len(refs) for _, refs in eligible)

        print(f"Found {len(eligible)} articles with {self.eligible_count} eligible references")

        self.emit_event("card_upkeep.scan.completed", {
            "base_files_found": len(eligible),
            "refs_eligible": self.eligible_count,
        })

        self.next(self.process_article, foreach="article_paths")

    @traced_step
    @step
    def process_article(self):
        """Process single article - create cards for eligible references.

        This step runs in parallel for each article in article_paths.
        Errors are captured per-article, not propagated.
        """
        article_path = self.input  # type: ignore[attr-defined] - metaflow FlowSpec, lacks stubs
        start_time = time.time()

        try:
            result = self._process_single_article(article_path)
            self.article_result = result

            self.emit_event("card_upkeep.article.completed", {
                "slug": result.slug,
                "success": result.success,
                "cards_created": result.cards_created,
                "duration_ms": result.duration_ms,
            })

        except Exception as e:
            # Capture error - don't propagate - allow other articles to succeed
            duration_ms = (time.time() - start_time) * 1000
            self.article_result = ArticleProcessResult(
                article_path=article_path,
                slug=Path(article_path).parent.name,
                success=False,
                error=str(e),
                duration_ms=duration_ms,
            )

            self.emit_event("card_upkeep.article.failed", {
                "slug": self.article_result.slug,
                "error": str(e),
                "guru_code": "#CUF.00000002.ARTICLEFAIL",
            })
            logger.warning(f"Article processing failed: {article_path}: {e}")

        self.next(self.join_articles)

    def _process_single_article(self, article_path: str) -> ArticleProcessResult:
        """Process a single article - create cards for eligible references.

        Args:
            article_path: Path to .base file

        Returns:
            ArticleProcessResult with success/failure and metrics
        """
        start_time = time.time()
        base_path = Path(article_path)
        slug = base_path.parent.name

        # Parse .base file
        data, references = parse_base_file(base_path)

        # Filter eligible references
        eligible = [
            ref for ref in references
            if ref.card_status in (CardStatus.UNKNOWN, CardStatus.PENDING)
        ]

        if not eligible:
            return ArticleProcessResult(
                article_path=article_path,
                slug=slug,
                success=True,
                cards_created=0,
                duration_ms=(time.time() - start_time) * 1000,
            )

        # Create cards via CollectionService
        if self.dry_run:
            # Dry run - just count
            return ArticleProcessResult(
                article_path=article_path,
                slug=slug,
                success=True,
                cards_created=0,
                cards_already_pending=len([r for r in eligible if r.card_status == CardStatus.PENDING]),
                ref_ids_processed=[r.ref_id for r in eligible],
                duration_ms=(time.time() - start_time) * 1000,
            )

        # Actually create cards
        try:
            card_ids, ref_ids = asyncio.get_event_loop().run_until_complete(
                self._create_cards_async(data, eligible)
            )
        except RuntimeError:
            card_ids, ref_ids = asyncio.new_event_loop().run_until_complete(
                self._create_cards_async(data, eligible)
            )

        return ArticleProcessResult(
            article_path=article_path,
            slug=slug,
            success=True,
            cards_created=len(card_ids),
            card_ids=card_ids,
            ref_ids_processed=ref_ids,
            duration_ms=(time.time() - start_time) * 1000,
        )

    async def _create_cards_async(
        self,
        base_data: dict[str, Any],
        references: list,
    ) -> tuple[list[str], list[str]]:
        """Create cards via CollectionService.

        Cards use brief_summary from .base file (LLM-generated summary of the
        cited passage or whole source). No fallbacks - brief_summary is required.

        Fail-fast on:
        - Article not registered in database
        - Missing collection mapping
        - Missing brief_summary for any reference
        - Card creation failure

        Args:
            base_data: Parsed .base file data (contains title, slug)
            references: List of ArticleReference objects

        Returns:
            Tuple of (card_ids, ref_ids) for created cards

        Raises:
            RuntimeError: On any schema mismatch or missing required data
        """
        import asyncpg
        from gaius.engine.services.collection_service import CollectionService

        db_url = _get_database_url()

        async with asyncpg.create_pool(db_url, min_size=1, max_size=3) as pool:
            service = CollectionService(pool)

            # Resolve article_id from slug (FAIL-FAST if not found)
            article_slug = base_data.get("slug", "")
            article = await service.get_article_by_slug(article_slug)
            if not article:
                raise RuntimeError(
                    f"Article '{article_slug}' not found in database.\n"
                    "  Guru Meditation: #CUF.00000011.NOARTICLE\n"
                    "  Fix: Run ArticleCurationFlow first to register article in DB"
                )

            # Use article's collection (1:1 mapping enforced by schema)
            if not article.collection_id:
                raise RuntimeError(
                    f"Article '{article_slug}' has no associated collection.\n"
                    "  Guru Meditation: #CUF.00000012.NOCOLLECTION\n"
                    "  Fix: Article-collection 1:1 mapping is broken, re-register article"
                )

            article_title = base_data.get("title", "Untitled")
            card_ids: list[str] = []
            ref_ids: list[str] = []

            for ref in references:
                # Skip if already pending (don't create duplicate cards)
                if ref.card_status == CardStatus.PENDING:
                    continue

                source_url = traceable_id_to_url(ref.traceable_id)
                source_type = extract_source_type(ref.traceable_id)

                # Use brief_summary from .base file (generated by ArticleCurationFlow)
                brief_summary = getattr(ref, "brief_summary", "") or ""

                if not brief_summary:
                    raise RuntimeError(
                        f"Missing brief_summary for {ref.ref_id}.\n"
                        "  Guru Meditation: #CUF.00000009.NOBRIEFSUMMARY\n"
                        "  Fix: Re-run ArticleCurationFlow to generate brief_summary fields"
                    )

                # Generate card title from first sentence of brief_summary
                card_title = _extract_title(brief_summary)
                if not card_title:
                    raise RuntimeError(
                        f"Could not extract title from brief_summary for {ref.ref_id}.\n"
                        "  Guru Meditation: #CUF.00000010.NOTITLE\n"
                        "  Fix: Check brief_summary content in .base file"
                    )

                summary = brief_summary

                card = await service.add_card(
                    collection_id=article.collection_id,
                    title=card_title,
                    summary=summary,
                    source_url=source_url,
                    source_type=source_type,
                    article_id=article.article_id,
                )
                card_ids.append(card.card_id)
                ref_ids.append(ref.ref_id)

            return card_ids, ref_ids

    @traced_step
    @step
    def join_articles(self, inputs):
        """Merge parallel article results.

        Aggregates success/failure metrics from all article branches.
        """
        # CRITICAL: merge_artifacts first to restore parent state
        self.merge_artifacts(inputs, exclude=["article_result"])  # type: ignore[attr-defined] - metaflow FlowSpec, lacks stubs

        # Collect all results
        self.article_results = [inp.article_result for inp in inputs]

        # Aggregate metrics
        succeeded = [r for r in self.article_results if r.success]
        failed = [r for r in self.article_results if not r.success]

        self.total_cards_created = sum(r.cards_created for r in succeeded)
        self.articles_succeeded = len(succeeded)
        self.articles_failed = len(failed)

        # Collect all ref_ids that need status update
        self.refs_to_update: dict[str, list[str]] = {}  # article_path -> ref_ids
        for result in succeeded:
            if result.ref_ids_processed:
                self.refs_to_update[result.article_path] = result.ref_ids_processed

        print(f"Processed {len(self.article_results)} articles: "
              f"{self.articles_succeeded} succeeded, {self.articles_failed} failed")
        print(f"Cards created: {self.total_cards_created}")

        self.emit_event("card_upkeep.batch.aggregated", {
            "articles_total": len(self.article_results),
            "articles_succeeded": self.articles_succeeded,
            "articles_failed": self.articles_failed,
            "cards_created": self.total_cards_created,
        })

        # Log failures for operator visibility
        for r in failed:
            logger.error(f"Article failed: {r.slug}: {r.error}")

        self.next(self.publish_batch)

    @traced_step
    @step
    def publish_batch(self):
        """Publish pending cards from the collection."""
        print(f"Publishing up to {self.publish_count} pending cards...")

        if self.dry_run:
            print("Dry run - skipping publish")
            self.cards_published = 0
            self.published_card_ids = []
            self.next(self.sync_to_kv)
            return

        try:
            result = asyncio.get_event_loop().run_until_complete(
                self._publish_cards_async()
            )
        except RuntimeError:
            result = asyncio.new_event_loop().run_until_complete(
                self._publish_cards_async()
            )

        self.cards_published = result.get("published_count", 0)
        self.published_card_ids = [c.get("card_id") for c in result.get("published", [])]

        print(f"Published {self.cards_published} cards")

        self.emit_event("card_upkeep.publish.completed", {
            "published_count": self.cards_published,
            "card_ids": self.published_card_ids,
        })

        self.next(self.sync_to_kv)

    async def _publish_cards_async(self) -> dict[str, Any]:
        """Publish pending cards via CollectionService."""
        import asyncpg
        from gaius.engine.services.collection_service import CollectionService

        db_url = _get_database_url()

        async with asyncpg.create_pool(db_url, min_size=1, max_size=3) as pool:
            service = CollectionService(pool)
            return await service.publish_and_sync(count=self.publish_count)

    @traced_step
    @step
    def sync_to_kv(self):
        """Sync published cards to Cloudflare KV.

        This step always runs (even if publish_batch synced) to ensure
        all published cards are visible on the landing page.
        """
        print("Syncing to Cloudflare KV...")

        if self.dry_run:
            print("Dry run - skipping KV sync")
            self.kv_sync_success = True
            self.kv_cards_synced = 0
            self.next(self.update_base_files)
            return

        try:
            result = asyncio.get_event_loop().run_until_complete(
                self._sync_to_kv_async()
            )
        except RuntimeError:
            result = asyncio.new_event_loop().run_until_complete(
                self._sync_to_kv_async()
            )

        self.kv_sync_success = result.get("success", False)
        self.kv_cards_synced = result.get("cards_synced", 0)

        if self.kv_sync_success:
            print(f"KV sync succeeded: {self.kv_cards_synced} cards")
        else:
            print("KV sync failed - cards created but not visible on landing page")
            self.emit_event("card_upkeep.kv.failed", {
                "guru_code": "#CUF.00000005.KVSYNCFAIL",
            })

        self.emit_event("card_upkeep.kv.completed", {
            "success": self.kv_sync_success,
            "cards_synced": self.kv_cards_synced,
        })

        self.next(self.update_base_files)

    async def _sync_to_kv_async(self) -> dict[str, Any]:
        """Sync to Cloudflare KV via CollectionService."""
        import asyncpg
        from gaius.engine.services.collection_service import CollectionService

        db_url = _get_database_url()

        async with asyncpg.create_pool(db_url, min_size=1, max_size=3) as pool:
            service = CollectionService(pool)
            return await service.sync_to_kv()

    @traced_step
    @step
    def update_base_files(self):
        """Update card_status in .base files.

        Sets:
        - unknown -> pending (if card created but not published)
        - pending -> published (if KV sync succeeded)
        """
        print("Updating .base files...")

        if self.dry_run:
            print("Dry run - skipping base file updates")
            self.base_files_updated = 0
            self.next(self.end)
            return

        # Determine target status based on KV sync result
        target_status = CardStatus.PUBLISHED if self.kv_sync_success else CardStatus.PENDING

        self.base_files_updated = 0
        for article_path, ref_ids in self.refs_to_update.items():
            try:
                base_path = Path(article_path)
                ref_updates = {ref_id: target_status for ref_id in ref_ids}
                updated = update_base_file(base_path, ref_updates)
                self.base_files_updated += 1

                self.emit_event("card_upkeep.base.updated", {
                    "article": base_path.parent.name,
                    "refs_updated": updated,
                    "new_status": target_status.value,
                })

            except Exception as e:
                logger.error(f"Failed to update {article_path}: {e}")
                self.emit_event("card_upkeep.base.update_failed", {
                    "article": Path(article_path).parent.name,
                    "error": str(e),
                    "guru_code": "#CUF.00000006.BASEUPDATE",
                })

        print(f"Updated {self.base_files_updated} .base files")

        self.next(self.end)

    @traced_step
    @step
    def end(self):
        """Emit lineage and report results."""
        # Handle case where we skipped to end (no eligible files)
        if not hasattr(self, "article_results"):
            self.article_results = []
            self.articles_succeeded = 0
            self.articles_failed = 0
            self.total_cards_created = 0
            self.cards_published = 0
            self.kv_sync_success = True
            self.base_files_updated = 0

        # Emit lineage COMPLETE
        outputs = []
        for result in getattr(self, "article_results", []):
            if result.success:
                outputs.append(Dataset.from_kb(result.article_path))

        self.emit_lineage_complete(outputs=outputs)

        # Summary
        print("\n" + "=" * 60)
        print("CARD UPKEEP COMPLETE")
        print("=" * 60)
        print(f"Articles processed: {len(self.article_results)}")
        print(f"  Succeeded: {self.articles_succeeded}")
        print(f"  Failed: {self.articles_failed}")
        print(f"Cards created: {self.total_cards_created}")
        print(f"Cards published: {getattr(self, 'cards_published', 0)}")
        print(f"KV sync: {'Success' if self.kv_sync_success else 'Failed'}")
        print(f"Base files updated: {self.base_files_updated}")

        # Final metrics event for longitudinal health tracking
        self.emit_event("card_upkeep.completed", {
            "articles_processed": len(self.article_results),
            "articles_succeeded": self.articles_succeeded,
            "articles_failed": self.articles_failed,
            "cards_created": self.total_cards_created,
            "cards_published": getattr(self, "cards_published", 0),
            "kv_sync_success": self.kv_sync_success,
            "base_files_updated": self.base_files_updated,
        })


if __name__ == "__main__":
    # Apply Metaflow config before running
    from gaius.flows.config import apply_metaflow_config
    apply_metaflow_config("local")
    CardUpkeepFlow()
