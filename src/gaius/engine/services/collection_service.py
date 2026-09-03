"""Collection service for the Gaius engine.

Manages curated content collections for public landing page:
- Create/manage collections with sources and cards
- Publish cards to Cloudflare KV for landing page
- Sync with Grok Collections API for X platform search
- Generate visualization data for 3D UMAP display

Collections contain:
- Sources: External content (arXiv, HuggingFace, etc.) with provenance
- Cards: Public-facing summaries linking to original sources
- Articles: Links to external publications (Substack, X threads)

Integrates with:
- PostgreSQL (collections schema) for state
- Cloudflare KV for public card data
- Grok Collections API for X platform sync
- KB for source material storage

Guru Meditation Codes:
- #COL.00000001.NOTFOUND: Collection not found
- #COL.00000002.DBFAIL: Database operation failed
- #COL.00000003.KVFAIL: Cloudflare KV publish failed
- #COL.00000004.GROKFAIL: Grok Collections API failed
- #COL.00000005.CARDFAIL: Card publish failed
- #COL.00000015.NOINFLOW: Featured collection empty and no public inflow URLs to admit
- #COL.00000016.NOENRICH: Pending cards exist but none passed LuxCore image + local open-weights gate
- #HX.00000001.CATALOGFAIL: Iceberg HX catalog not reachable
- #HX.00000002.TABLEFAIL: Could not access/create Iceberg table
- #HX.00000003.WRITEFAIL: Failed to append record to Iceberg
"""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, AsyncIterator

import asyncpg
from gaius.core.budgets import REASONING_MAX_TOKENS, EXTERNAL_MAX_TOKENS

logger = logging.getLogger(__name__)


# Card page contract (landing click-through):
#   required — LuxCore image + local open-weights panel
#   optional — Brave / Cerebras panels (API availability and budget)
REQUIRED_CARD_SUMMARY = "open_weights"
OPTIONAL_CARD_SUMMARIES = ("frontier", "cerebras")


def public_card_source_type(feed_source_type: str) -> str:
    """Map feed_sources.source_type onto collections.cards.source_type."""
    if feed_source_type in ("arxiv", "biorxiv"):
        return "arxiv"
    return "web"


class CollectionError(Exception):
    """Collection service error with Guru Meditation code."""

    def __init__(self, message: str, guru_code: str | None = None):
        super().__init__(message)
        self.guru_code = guru_code

    def __str__(self) -> str:
        if self.guru_code:
            return f"{super().__str__()}\n  Guru Meditation: {self.guru_code}"
        return super().__str__()


@dataclass
class Collection:
    """A curated content collection."""

    collection_id: str
    slug: str
    name: str
    description: str = ""
    status: str = "draft"  # draft, active, archived
    featured: bool = False
    grok_collection_id: str | None = None
    grok_last_sync_at: datetime | None = None
    series_enabled: bool = True
    kb_path: str = ""
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for serialization."""
        return {
            "collection_id": self.collection_id,
            "slug": self.slug,
            "name": self.name,
            "description": self.description,
            "status": self.status,
            "featured": self.featured,
            "grok_collection_id": self.grok_collection_id,
            "grok_last_sync_at": self.grok_last_sync_at.isoformat() if self.grok_last_sync_at else None,
            "series_enabled": self.series_enabled,
            "kb_path": self.kb_path,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


@dataclass
class Card:
    """A public-facing content card."""

    card_id: str
    collection_id: str
    title: str
    summary: str
    source_url: str
    source_type: str  # arxiv, huggingface, cloudera, web, x_bookmark
    image_url: str | None = None
    status: str = "pending"  # pending, published, archived
    published_at: datetime | None = None
    source_date: date | None = None  # Original source publication date (e.g., arXiv submission)
    sequence: int | None = None
    article_id: str | None = None
    prev_card_id: str | None = None
    next_card_id: str | None = None
    kb_path: str | None = None
    created_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for serialization."""
        return {
            "card_id": self.card_id,
            "collection_id": self.collection_id,
            "title": self.title,
            "summary": self.summary,
            "source_url": self.source_url,
            "source_type": self.source_type,
            "image_url": self.image_url,
            "status": self.status,
            "published_at": self.published_at.isoformat() if self.published_at else None,
            "sequence": self.sequence,
            "article_id": self.article_id,
            "prev_card_id": self.prev_card_id,
            "next_card_id": self.next_card_id,
            "kb_path": self.kb_path,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    def to_public_dict(self) -> dict[str, Any]:
        """Convert to dict for public API (Cloudflare KV).

        Uses snake_case keys to match both the landing page worker
        and the gRPC servicer expectations.
        """
        return {
            "card_id": self.card_id,
            "collection_id": self.collection_id,
            "title": self.title,
            "summary": self.summary,
            "source_url": self.source_url,
            "source_type": self.source_type,
            "image_url": self.image_url,
            "status": self.status,
            "published_at": self.published_at.isoformat() if self.published_at else None,
            "source_date": self.source_date.isoformat() if self.source_date else None,
            "sequence": self.sequence,
        }


@dataclass
class Source:
    """Detailed provenance for a card."""

    source_id: str
    card_id: str
    provenance_url: str
    provenance_traceable_id: str | None = None
    source_type: str = "web"
    excerpt_text: str | None = None
    excerpt_page: int | None = None
    excerpt_section: str | None = None
    excerpt_char_start: int | None = None
    excerpt_char_end: int | None = None
    ingested_via: str | None = None
    ingested_at: datetime | None = None
    kb_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for serialization."""
        return {
            "source_id": self.source_id,
            "card_id": self.card_id,
            "provenance_url": self.provenance_url,
            "provenance_traceable_id": self.provenance_traceable_id,
            "source_type": self.source_type,
            "excerpt_text": self.excerpt_text,
            "excerpt_page": self.excerpt_page,
            "excerpt_section": self.excerpt_section,
            "excerpt_char_start": self.excerpt_char_start,
            "excerpt_char_end": self.excerpt_char_end,
            "ingested_via": self.ingested_via,
            "ingested_at": self.ingested_at.isoformat() if self.ingested_at else None,
            "kb_path": self.kb_path,
        }


@dataclass
class Article:
    """A KB article tracked in the database."""

    article_id: str
    slug: str
    title: str
    status: str = "pending"  # pending, researching, drafting, review, published, abandoned
    kb_path: str = ""
    collection_id: str | None = None
    current_version: int = 0
    zk_count: int = 0
    sources_count: int = 0
    arxiv_categories: list[str] | None = None
    keywords: list[str] | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for serialization."""
        return {
            "article_id": self.article_id,
            "slug": self.slug,
            "title": self.title,
            "status": self.status,
            "kb_path": self.kb_path,
            "collection_id": self.collection_id,
            "current_version": self.current_version,
            "zk_count": self.zk_count,
            "sources_count": self.sources_count,
            "arxiv_categories": self.arxiv_categories,
            "keywords": self.keywords,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


@dataclass
class ArticleCurationEvent:
    """Progress event from ArticleCurationFlow."""

    event_id: int
    run_id: str
    step: str  # start, select, research, acquire, summarize, draft, base, cards, complete, failed
    step_number: int
    total_steps: int
    progress: float  # 0.0 - 1.0
    message: str
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_payload(cls, payload: str) -> "ArticleCurationEvent":
        """Parse from pg_notify JSON payload."""
        import json
        data = json.loads(payload)
        return cls(
            event_id=data.get("event_id", 0),
            run_id=data["run_id"],
            step=data["step"],
            step_number=data["step_number"],
            total_steps=data.get("total_steps", 9),
            progress=data.get("progress", 0.0),
            message=data.get("message", ""),
            metadata=data.get("metadata", {}),
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for serialization."""
        return {
            "event_id": self.event_id,
            "run_id": self.run_id,
            "step": self.step,
            "step_number": self.step_number,
            "total_steps": self.total_steps,
            "progress": self.progress,
            "message": self.message,
            "metadata": self.metadata,
        }


@dataclass
class CollectionConfig:
    """Configuration for Collection service."""

    # KB root path for artifacts
    kb_root: str = "build/dev"

    # Cloudflare KV settings
    cf_account_id: str = ""
    cf_api_token: str = ""
    cf_kv_namespace_id: str = ""

    # Grok Collections API settings
    grok_api_key: str = ""

    # Publish settings
    default_publish_count: int = 3
    max_cards_per_publish: int = 10


class CollectionService:
    """Collection service managing curated content for public landing page.

    Provides:
    1. Collection CRUD operations
    2. Card management with publish workflow
    3. Cloudflare KV synchronization
    4. Grok Collections API integration
    """

    def __init__(
        self,
        pool: asyncpg.Pool,
        config: CollectionConfig | None = None,
    ):
        """Initialize service with database pool."""
        self._pool = pool
        self._config = config or CollectionConfig()
        from gaius.engine.services.publishing_axis import PublishingAxis

        self._axis = PublishingAxis(pool)

    def start_publishing_axis(self) -> None:
        self._axis.start()

    # =========================================================================
    # Collection Operations
    # =========================================================================

    async def create_collection(
        self,
        slug: str,
        name: str,
        description: str = "",
        featured: bool = False,
    ) -> Collection:
        """Create a new collection.

        Args:
            slug: URL-friendly identifier
            name: Display name
            description: Optional description
            featured: Whether this is the featured collection (only one allowed)

        Returns:
            Created Collection object
        """
        collection_id = f"col_{uuid.uuid4().hex[:12]}"
        kb_path = f"current/collections/{slug}/"
        now = datetime.now(timezone.utc)

        async with self._pool.acquire() as conn:
            # If featured, unfeatured any existing featured collection
            if featured:
                await conn.execute(
                    "UPDATE collections.collections SET featured = FALSE WHERE featured = TRUE"
                )

            await conn.execute(
                """
                INSERT INTO collections.collections
                (collection_id, slug, name, description, featured, kb_path, created_at, updated_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $7)
                """,
                collection_id, slug, name, description, featured, kb_path, now,
            )

        return Collection(
            collection_id=collection_id,
            slug=slug,
            name=name,
            description=description,
            featured=featured,
            kb_path=kb_path,
            created_at=now,
            updated_at=now,
        )

    async def get_collection(self, collection_id: str) -> Collection | None:
        """Get a collection by ID."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM collections.collections WHERE collection_id = $1",
                collection_id,
            )
            if not row:
                return None
            return self._row_to_collection(row)

    async def get_collection_by_slug(self, slug: str) -> Collection | None:
        """Get a collection by slug."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM collections.collections WHERE slug = $1",
                slug,
            )
            if not row:
                return None
            return self._row_to_collection(row)

    async def get_featured_collection(self) -> Collection | None:
        """Get the featured collection for the landing page."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM collections.collections WHERE featured = TRUE"
            )
            if not row:
                return None
            return self._row_to_collection(row)

    async def list_collections(
        self,
        status: str | None = None,
        limit: int = 50,
    ) -> list[Collection]:
        """List collections with optional status filter."""
        async with self._pool.acquire() as conn:
            if status:
                rows = await conn.fetch(
                    """
                    SELECT * FROM collections.collections
                    WHERE status = $1
                    ORDER BY created_at DESC
                    LIMIT $2
                    """,
                    status, limit,
                )
            else:
                rows = await conn.fetch(
                    """
                    SELECT * FROM collections.collections
                    ORDER BY created_at DESC
                    LIMIT $1
                    """,
                    limit,
                )
            return [self._row_to_collection(row) for row in rows]

    async def set_featured(self, collection_id: str) -> None:
        """Set a collection as the featured collection."""
        async with self._pool.acquire() as conn:
            # Clear existing featured
            await conn.execute(
                "UPDATE collections.collections SET featured = FALSE WHERE featured = TRUE"
            )
            # Set new featured
            result = await conn.execute(
                "UPDATE collections.collections SET featured = TRUE WHERE collection_id = $1",
                collection_id,
            )
            if result == "UPDATE 0":
                raise CollectionError(
                    f"Collection not found: {collection_id}",
                    guru_code="#COL.00000001.NOTFOUND",
                )

    async def update_grok_collection_id(
        self,
        collection_id: str,
        grok_collection_id: str,
    ) -> None:
        """Update grok_collection_id and grok_last_sync_at for a collection.

        Called by ArticleCurationFlow after creating or finding a Grok collection
        to persist the 1:1 mapping between local and xAI collections.

        Args:
            collection_id: Local PostgreSQL collection ID
            grok_collection_id: xAI/Grok collection ID

        Raises:
            CollectionError: If collection not found
        """
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                """
                UPDATE collections.collections
                SET grok_collection_id = $2,
                    grok_last_sync_at = NOW(),
                    updated_at = NOW()
                WHERE collection_id = $1
                """,
                collection_id, grok_collection_id,
            )
            if result == "UPDATE 0":
                raise CollectionError(
                    f"Collection not found: {collection_id}",
                    guru_code="#COL.00000001.NOTFOUND",
                )
            logger.info(
                f"Updated collection {collection_id} with grok_collection_id: {grok_collection_id}"
            )

    async def sync_collection_to_grok(
        self,
        collection_id: str,
        kb_root: str | None = None,
    ) -> dict[str, Any]:
        """Sync a collection to Grok Collections API (standalone).

        Reads source files from the KB disk and uploads them to xAI
        Grok Collections. Creates the Grok collection if needed.
        Persists grok_collection_id to PostgreSQL (fail-fast).

        This is independent of the ArticleCurationFlow — any collection
        can be synced at any time.

        Args:
            collection_id: Local PostgreSQL collection ID
            kb_root: KB root directory (defaults to GAIUS_KB_ROOT)

        Returns:
            Dict with collection_id, documents uploaded, etc.

        Raises:
            CollectionError: If collection/article not found or sync fails
            RuntimeError: If XAI_MANAGEMENT_KEY not set

        Guru Meditation: #COL.00000010.GROKSYNC
        """
        import os
        from pathlib import Path

        import yaml
        from xai_sdk import Client as XAIClient
        from xai_sdk.collections import FieldDefinition

        # Step 1: Get collection + article from Postgres
        collection = await self.get_collection(collection_id)
        if not collection:
            raise CollectionError(
                f"Collection not found: {collection_id}",
                guru_code="#COL.00000001.NOTFOUND",
            )

        # Find the article linked to this collection
        article = None
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM collections.articles WHERE collection_id = $1",
                collection_id,
            )
            if row:
                article = self._row_to_article(row)

        if not article:
            raise CollectionError(
                f"No article linked to collection {collection_id}.\n"
                "  Guru Meditation: #COL.00000010.GROKSYNC\n"
                "  Grok sync requires an article with source files on disk",
                guru_code="#COL.00000010.GROKSYNC",
            )

        # Step 2: Read source files from KB disk
        if not kb_root:
            kb_root = os.environ.get("GAIUS_KB_ROOT", "build/dev")
        sources_dir = Path(kb_root) / article.kb_path / "sources"

        if not sources_dir.exists():
            raise CollectionError(
                f"Sources directory not found: {sources_dir}\n"
                "  Guru Meditation: #COL.00000010.GROKSYNC\n"
                f"  Expected source files at {sources_dir}",
                guru_code="#COL.00000010.GROKSYNC",
            )

        source_files = sorted(sources_dir.glob("*.md"))
        if not source_files:
            raise CollectionError(
                f"No source files found in {sources_dir}\n"
                "  Guru Meditation: #COL.00000010.GROKSYNC\n"
                "  Run article curation to acquire sources first",
                guru_code="#COL.00000010.GROKSYNC",
            )

        # Step 3: Parse source files (YAML frontmatter + content)
        sources = []
        for sf in source_files:
            content = sf.read_text()
            frontmatter = {}
            body = content

            # Parse YAML frontmatter if present
            if content.startswith("---"):
                parts = content.split("---", 2)
                if len(parts) >= 3:
                    frontmatter = yaml.safe_load(parts[1]) or {}
                    body = parts[2].strip()

            sources.append({
                "source_id": sf.stem,
                "source_type": frontmatter.get("source_type", "web"),
                "url": frontmatter.get("url", ""),
                "title": frontmatter.get("title", sf.stem),
                "content": body,
            })

        # Step 4: Create/find Grok collection via xai-sdk
        from gaius.core.config import get_config

        mgmt_key = get_config().providers.xai.management_key
        if not mgmt_key:
            raise RuntimeError(
                "XAI_MANAGEMENT_KEY not configured — required for Grok Collections.\n"
                "  Guru Meditation: #COL.00000011.NOMGMTKEY\n"
                "  Create a Management API Key at https://console.x.ai\n"
                "  Set XAI_MANAGEMENT_KEY environment variable"
            )

        client = XAIClient(management_api_key=mgmt_key)
        try:
            collection_name = f"gaius-article-{article.slug}"
            grok_collection_id = collection.grok_collection_id

            # Check for existing collection on xAI
            if not grok_collection_id:
                collections_resp = client.collections.list()
                for c in collections_resp.collections:
                    if c.collection_name == collection_name:
                        grok_collection_id = c.collection_id
                        logger.info(f"Found existing Grok collection: {grok_collection_id}")
                        break

            # Create if not found
            if not grok_collection_id:
                logger.info(f"Creating Grok collection: {collection_name}")
                grok_col = client.collections.create(
                    name=collection_name,
                    model_name="grok-embedding-small",
                    field_definitions=[
                        FieldDefinition(key="source_type", required=False, inject_into_chunk=True, unique=False),
                        FieldDefinition(key="source_id", required=False, inject_into_chunk=False, unique=True),
                        FieldDefinition(key="url", required=False, inject_into_chunk=True, unique=False),
                    ],
                )
                grok_collection_id = grok_col.collection_id
                logger.info(f"Created Grok collection: {grok_collection_id}")

            # Step 5: Upload source documents
            upload_results = []
            for source in sources:
                doc_content = f"# {source['title']}\n\n"
                doc_content += f"Source: {source['url']}\n"
                doc_content += f"Type: {source['source_type']}\n\n"
                doc_content += source["content"]

                document = client.collections.upload_document(
                    collection_id=grok_collection_id,
                    name=f"{source['source_id']}.md",
                    data=doc_content.encode("utf-8"),
                    fields={
                        "source_type": source["source_type"],
                        "source_id": source["source_id"],
                        "url": source["url"],
                    },
                )

                upload_results.append({
                    "source_id": source["source_id"],
                    "status": "uploaded",
                    "document_id": getattr(document, "file_id", None),
                })

            # Step 6: Persist grok_collection_id (fail-fast)
            await self.update_grok_collection_id(collection_id, grok_collection_id)

            return {
                "collection_id": collection_id,
                "grok_collection_id": grok_collection_id,
                "collection_name": collection_name,
                "documents_uploaded": len(upload_results),
                "upload_results": upload_results,
            }

        finally:
            client.close()

    # =========================================================================
    # Article Operations
    # =========================================================================

    async def create_article_with_collection(
        self,
        slug: str,
        title: str,
        kb_path: str,
        arxiv_categories: list[str] | None = None,
        keywords: list[str] | None = None,
    ) -> tuple[Article, Collection]:
        """Create an article with its 1:1 collection atomically.

        Uses same slug for both article and collection. This enforces
        the 1:1 mapping between articles and collections.

        Args:
            slug: URL-friendly identifier (same for article and collection)
            title: Display title
            kb_path: KB path to article directory
            arxiv_categories: Optional arXiv categories for research hints
            keywords: Optional keywords for research hints

        Returns:
            Tuple of (Article, Collection) objects

        Raises:
            CollectionError: If creation fails
        """
        async with self._pool.acquire() as conn:
            try:
                row = await conn.fetchrow(
                    """
                    SELECT * FROM collections.create_article_with_collection($1, $2, $3, $4, $5)
                    """,
                    slug, title, kb_path, arxiv_categories, keywords,
                )

                if not row:
                    raise CollectionError(
                        f"Failed to create article: {slug}",
                        guru_code="#COL.00000007.ARTICLEFAIL",
                    )

                article_id = row["article_id"]
                collection_id = row["collection_id"]

                # Fetch full objects
                article = await self.get_article(article_id)
                collection = await self.get_collection(collection_id)

                if not article or not collection:
                    raise CollectionError(
                        f"Article or collection not found after creation: {slug}",
                        guru_code="#COL.00000007.ARTICLEFAIL",
                    )

                logger.info(f"Created article {article_id} with collection {collection_id}")
                return article, collection

            except asyncpg.UniqueViolationError as e:
                raise CollectionError(
                    f"Article or collection with slug '{slug}' already exists.\n"
                    f"  Detail: {e}",
                    guru_code="#COL.00000008.DUPLICATE",
                ) from e

    async def get_article(self, article_id: str) -> Article | None:
        """Get an article by ID."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM collections.articles WHERE article_id = $1",
                article_id,
            )
            if not row:
                return None
            return self._row_to_article(row)

    async def get_article_by_slug(self, slug: str) -> Article | None:
        """Get an article by slug.

        Used by CardUpkeepFlow to resolve article_id before creating cards.
        Fail-fast if article not found in database.
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM collections.articles WHERE slug = $1",
                slug,
            )
            if not row:
                return None
            return self._row_to_article(row)

    async def list_articles(
        self,
        status: str | None = None,
        limit: int = 50,
    ) -> list[Article]:
        """List articles with optional status filter."""
        async with self._pool.acquire() as conn:
            if status:
                rows = await conn.fetch(
                    """
                    SELECT * FROM collections.articles
                    WHERE status = $1
                    ORDER BY created_at DESC
                    LIMIT $2
                    """,
                    status, limit,
                )
            else:
                rows = await conn.fetch(
                    """
                    SELECT * FROM collections.articles
                    ORDER BY created_at DESC
                    LIMIT $1
                    """,
                    limit,
                )
            return [self._row_to_article(row) for row in rows]

    async def update_article_stats(
        self,
        article_id: str,
        zk_count: int | None = None,
        sources_count: int | None = None,
        current_version: int | None = None,
    ) -> None:
        """Update article statistics.

        Called after zettelkasten notes or sources are added.
        """
        updates = []
        params: list[str | int] = [article_id]
        param_idx = 2

        if zk_count is not None:
            updates.append(f"zk_count = ${param_idx}")
            params.append(zk_count)
            param_idx += 1

        if sources_count is not None:
            updates.append(f"sources_count = ${param_idx}")
            params.append(sources_count)
            param_idx += 1

        if current_version is not None:
            updates.append(f"current_version = ${param_idx}")
            params.append(current_version)
            param_idx += 1

        if not updates:
            return

        async with self._pool.acquire() as conn:
            await conn.execute(
                f"""
                UPDATE collections.articles
                SET {', '.join(updates)}, updated_at = NOW()
                WHERE article_id = $1
                """,
                *params,
            )

    # =========================================================================
    # Card Operations
    # =========================================================================

    async def add_card(
        self,
        collection_id: str,
        title: str,
        summary: str,
        source_url: str,
        source_type: str,
        image_url: str | None = None,
        sequence: int | None = None,
        article_id: str | None = None,
        source_date: date | None = None,
        kb_path: str | None = None,
        zettle_slug: str | None = None,
    ) -> Card:
        """Add a card to a collection.

        Args:
            collection_id: Parent collection ID
            title: Card title
            summary: 1-2 sentence summary
            source_url: Link to original PUBLIC source
            source_type: Type of source (arxiv, huggingface, etc.)
            image_url: Optional image URL
            sequence: Optional ordering sequence
            article_id: Article ID for FK relationship
            source_date: Original source publication date
            kb_path: Path to source file in KB
            zettle_slug: Zettelkasten slug current when card was created

        Returns:
            Created Card object
        """
        card_id = f"card_{uuid.uuid4().hex[:12]}"
        now = datetime.now(timezone.utc)

        async with self._pool.acquire() as conn:
            # Verify collection exists
            exists = await conn.fetchval(
                "SELECT 1 FROM collections.collections WHERE collection_id = $1",
                collection_id,
            )
            if not exists:
                raise CollectionError(
                    f"Collection not found: {collection_id}",
                    guru_code="#COL.00000001.NOTFOUND",
                )

            # Auto-assign sequence if not provided
            if sequence is None:
                max_seq = await conn.fetchval(
                    """
                    SELECT COALESCE(MAX(sequence), 0) + 1
                    FROM collections.cards
                    WHERE collection_id = $1
                    """,
                    collection_id,
                )
                sequence = max_seq

            await conn.execute(
                """
                INSERT INTO collections.cards
                (card_id, collection_id, title, summary, source_url, source_type,
                 image_url, sequence, article_id, source_date, kb_path, zettle_slug,
                 created_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
                """,
                card_id, collection_id, title, summary, source_url, source_type,
                image_url, sequence, article_id, source_date, kb_path, zettle_slug,
                now,
            )

        return Card(
            card_id=card_id,
            collection_id=collection_id,
            title=title,
            summary=summary,
            source_url=source_url,
            source_type=source_type,
            image_url=image_url,
            sequence=sequence,
            article_id=article_id,
            source_date=source_date,
            kb_path=kb_path,
            created_at=now,
        )

    async def count_featured_pending(self) -> int:
        """Pending cards in the featured collection (publish clock inventory)."""
        async with self._pool.acquire() as conn:
            n = await conn.fetchval(
                """
                SELECT count(*) FROM collections.cards c
                JOIN collections.collections col
                  ON col.collection_id = c.collection_id
                WHERE col.featured = TRUE AND c.status = 'pending'
                """
            )
        return int(n or 0)

    async def count_featured_ready(self) -> int:
        """Pending featured cards with LuxCore image + local open-weights."""
        async with self._pool.acquire() as conn:
            n = await conn.fetchval(
                """
                SELECT count(*) FROM collections.cards c
                JOIN collections.collections col
                  ON col.collection_id = c.collection_id
                WHERE col.featured = TRUE AND c.status = 'pending'
                  AND c.image_url IS NOT NULL AND c.image_url != ''
                  AND EXISTS (
                      SELECT 1 FROM collections.card_summaries cs
                       WHERE cs.card_id = c.card_id
                         AND cs.summary_type = 'open_weights'
                  )
                """
            )
        return int(n or 0)

    async def admit_public_inflow(self, limit: int = 6) -> int:
        """Create pending featured cards from public feed URLs (no KB paths).

        article_curate has been blocked (YK admit/disk) since March, so
        publish_cards was KV-healthy with published_count=0. This admits
        arXiv/web items already fetched by feed_check.
        """
        limit = max(1, min(int(limit), 24))
        async with self._pool.acquire() as conn:
            featured = await conn.fetchrow(
                """
                SELECT c.collection_id, a.article_id
                  FROM collections.collections c
                  JOIN collections.articles a ON a.collection_id = c.collection_id
                 WHERE c.featured = TRUE
                 LIMIT 1
                """
            )
            if not featured:
                raise CollectionError(
                    "No featured collection/article.\n  Guru: #COL.00000001.NOTFOUND",
                    guru_code="#COL.00000001.NOTFOUND",
                )
            featured_id = str(featured["collection_id"])
            article_id = str(featured["article_id"])
            rows = await conn.fetch(
                """
                SELECT c.title,
                       COALESCE(NULLIF(c.summary, ''), LEFT(c.title, 180)) AS summary,
                       c.url,
                       s.source_type,
                       s.name AS feed_name,
                       COALESCE(c.published_at, c.fetched_at) AS source_ts
                  FROM content_items c
                  JOIN feed_sources s ON s.id = c.source_id
                 WHERE c.url ~ '^https?://'
                   AND NOT COALESCE(c.summary_excluded, false)
                   AND COALESCE(c.llm_quality_score, 0) >= 50
                   AND c.fetched_at > NOW() - INTERVAL '21 days'
                   AND s.name = ANY($1::text[])
                   AND NOT EXISTS (
                       SELECT 1 FROM collections.cards k
                        WHERE k.source_url = c.url
                   )
                 ORDER BY
                   CASE s.name WHEN 'arxiv_cs_dc' THEN 0 ELSE 1 END,
                   c.fetched_at DESC
                 LIMIT $2
                """,
                ["arxiv_cs_dc", "temporal_blog", "databricks_blog"],
                limit,
            )

        admitted = 0
        for row in rows:
            url = str(row["url"])
            title = str(row["title"] or "").strip() or url
            summary = str(row["summary"] or title)[:400]
            src_type = public_card_source_type(str(row["source_type"] or "web"))
            ts = row["source_ts"]
            src_date = ts.date() if hasattr(ts, "date") else None
            card = await self.add_card(
                collection_id=featured_id,
                title=title[:300],
                summary=summary,
                source_url=url,
                source_type=src_type,
                article_id=article_id,
                source_date=src_date,
                kb_path=None,
            )
            await self.add_source(
                source_id=f"src_inflow_{uuid.uuid4().hex[:12]}",
                card_id=card.card_id,
                provenance_url=url,
                source_type=src_type,
                ingested_via="public_inflow",
                kb_path=None,
            )
            admitted += 1
            logger.info("Admitted public card %s %s", card.card_id, title[:60])
        return admitted

    async def add_source(
        self,
        source_id: str,
        card_id: str,
        provenance_url: str,
        source_type: str,
        provenance_traceable_id: str | None = None,
        excerpt_text: str | None = None,
        excerpt_page: int | None = None,
        excerpt_section: str | None = None,
        excerpt_char_start: int | None = None,
        excerpt_char_end: int | None = None,
        ingested_via: str | None = None,
        kb_path: str | None = None,
    ) -> Source:
        """Add a provenance source record for a card.

        Every card must have at least one source record linking it to
        the original content. This is the provenance chain.

        Args:
            source_id: Unique source identifier (e.g., src_arxiv_abc123)
            card_id: Parent card ID (must exist)
            provenance_url: Original source URL
            source_type: Type (arxiv, web, huggingface, etc.)
            provenance_traceable_id: TraceableId URI (e.g., arxiv://2401.12345)
            excerpt_text: Key excerpt for citation
            excerpt_page: Page number of excerpt
            excerpt_section: Section heading of excerpt
            excerpt_char_start: Start character offset
            excerpt_char_end: End character offset
            ingested_via: How source was acquired (article_curation, web_search, etc.)
            kb_path: Path to source file in KB

        Returns:
            Created Source object

        Raises:
            CollectionError: If card not found or insert fails
        """
        now = datetime.now(timezone.utc)

        async with self._pool.acquire() as conn:
            # Verify card exists
            exists = await conn.fetchval(
                "SELECT 1 FROM collections.cards WHERE card_id = $1",
                card_id,
            )
            if not exists:
                raise CollectionError(
                    f"Card not found: {card_id}",
                    guru_code="#COL.00000005.CARDFAIL",
                )

            # Build excerpt_char_range from start/end if provided
            char_range = None
            if excerpt_char_start is not None and excerpt_char_end is not None:
                # asyncpg handles Range types via asyncpg.Range
                from asyncpg import Range
                char_range = Range(excerpt_char_start, excerpt_char_end)

            await conn.execute(
                """
                INSERT INTO collections.sources
                (source_id, card_id, provenance_url, provenance_traceable_id,
                 source_type, excerpt_text, excerpt_page, excerpt_section,
                 excerpt_char_range, ingested_via, ingested_at, kb_path)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
                ON CONFLICT (source_id) DO NOTHING
                """,
                source_id, card_id, provenance_url, provenance_traceable_id,
                source_type, excerpt_text, excerpt_page, excerpt_section,
                char_range, ingested_via, now, kb_path,
            )

        return Source(
            source_id=source_id,
            card_id=card_id,
            provenance_url=provenance_url,
            provenance_traceable_id=provenance_traceable_id,
            source_type=source_type,
            excerpt_text=excerpt_text,
            excerpt_page=excerpt_page,
            excerpt_section=excerpt_section,
            excerpt_char_start=excerpt_char_start,
            excerpt_char_end=excerpt_char_end,
            ingested_via=ingested_via,
            ingested_at=now,
            kb_path=kb_path,
        )

    async def get_card(self, card_id: str) -> Card | None:
        """Get a card by ID."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM collections.cards WHERE card_id = $1",
                card_id,
            )
            if not row:
                return None
            return self._row_to_card(row)

    async def list_cards(
        self,
        collection_id: str,
        status: str | None = None,
        limit: int = 100,
    ) -> list[Card]:
        """List cards in a collection."""
        async with self._pool.acquire() as conn:
            if status:
                rows = await conn.fetch(
                    """
                    SELECT * FROM collections.cards
                    WHERE collection_id = $1 AND status = $2
                    ORDER BY sequence ASC, created_at ASC
                    LIMIT $3
                    """,
                    collection_id, status, limit,
                )
            else:
                rows = await conn.fetch(
                    """
                    SELECT * FROM collections.cards
                    WHERE collection_id = $1
                    ORDER BY sequence ASC, created_at ASC
                    LIMIT $2
                    """,
                    collection_id, limit,
                )
            return [self._row_to_card(row) for row in rows]

    async def get_published_cards(
        self,
        collection_id: str | None = None,
        limit: int = 50,
    ) -> list[Card]:
        """Get published cards for landing page.

        If collection_id is None, uses the featured collection.
        """
        async with self._pool.acquire() as conn:
            if collection_id:
                rows = await conn.fetch(
                    """
                    SELECT * FROM collections.cards
                    WHERE collection_id = $1 AND status = 'published'
                    ORDER BY published_at DESC
                    LIMIT $2
                    """,
                    collection_id, limit,
                )
            else:
                # Get from featured collection
                rows = await conn.fetch(
                    """
                    SELECT c.* FROM collections.cards c
                    JOIN collections.collections col ON c.collection_id = col.collection_id
                    WHERE col.featured = TRUE AND c.status = 'published'
                    ORDER BY c.published_at DESC
                    LIMIT $1
                    """,
                    limit,
                )
            return [self._row_to_card(row) for row in rows]

    # =========================================================================
    # Publish Operations
    # =========================================================================

    async def publish_cards(
        self,
        count: int = 3,
        collection_id: str | None = None,
    ) -> list[Card]:
        """Publish pending cards from a collection with diversity.

        Selects cards using round-robin across articles and source types
        to maintain variety on the landing page.

        Args:
            count: Number of cards to publish (default: 3)
            collection_id: Collection to publish from (default: featured)

        Returns:
            List of newly published cards
        """
        count = min(count, self._config.max_cards_per_publish)

        async with self._pool.acquire() as conn:
            if collection_id:
                # Publish from specific collection with diversity
                # Round-robin across articles and source types for varied content
                # LuxCore image + local open-weights (Brave/Cerebras optional)
                rows = await conn.fetch(
                    """
                    WITH enriched_filter AS (
                        -- LuxCore image + local open-weights (Brave/Cerebras optional)
                        SELECT c.card_id
                        FROM collections.cards c
                        WHERE c.collection_id = $1 AND c.status = 'pending'
                          AND c.image_url IS NOT NULL AND c.image_url != ''
                          AND EXISTS (
                              SELECT 1 FROM collections.card_summaries cs
                               WHERE cs.card_id = c.card_id
                                 AND cs.summary_type = 'open_weights'
                          )
                    ),
                    pending_ranked AS (
                        -- Rank cards within each article/source_type combo
                        -- to enable round-robin selection across diverse sources
                        SELECT
                            c.card_id,
                            c.article_id,
                            c.source_type,
                            ROW_NUMBER() OVER (
                                PARTITION BY c.article_id, c.source_type
                                ORDER BY c.created_at ASC
                            ) as rank_in_group
                        FROM collections.cards c
                        WHERE c.card_id IN (SELECT card_id FROM enriched_filter)
                    ),
                    diverse_pending AS (
                        -- Select round-robin: one from each article/type combo before repeating
                        SELECT card_id
                        FROM pending_ranked
                        ORDER BY rank_in_group, article_id, source_type
                        LIMIT $2
                        FOR UPDATE
                    )
                    UPDATE collections.cards
                    SET status = 'published', published_at = NOW(), updated_at = NOW()
                    WHERE card_id IN (SELECT card_id FROM diverse_pending)
                    RETURNING *
                    """,
                    collection_id, count,
                )
            else:
                # Publish from featured collection with diversity
                # Round-robin across articles and source types for varied landing page
                # LuxCore image + local open-weights (Brave/Cerebras optional)
                rows = await conn.fetch(
                    """
                    WITH featured_col AS (
                        SELECT collection_id FROM collections.collections
                        WHERE featured = TRUE
                    ),
                    enriched_filter AS (
                        -- LuxCore image + local open-weights (Brave/Cerebras optional)
                        SELECT c.card_id
                        FROM collections.cards c
                        JOIN featured_col fc ON c.collection_id = fc.collection_id
                        WHERE c.status = 'pending'
                          AND c.image_url IS NOT NULL AND c.image_url != ''
                          AND EXISTS (
                              SELECT 1 FROM collections.card_summaries cs
                               WHERE cs.card_id = c.card_id
                                 AND cs.summary_type = 'open_weights'
                          )
                    ),
                    pending_ranked AS (
                        -- Rank cards within each article/source_type combo
                        SELECT
                            c.card_id,
                            c.article_id,
                            c.source_type,
                            ROW_NUMBER() OVER (
                                PARTITION BY c.article_id, c.source_type
                                ORDER BY c.created_at ASC
                            ) as rank_in_group
                        FROM collections.cards c
                        WHERE c.card_id IN (SELECT card_id FROM enriched_filter)
                    ),
                    diverse_pending AS (
                        -- Select round-robin: one from each article/type combo before repeating
                        SELECT card_id
                        FROM pending_ranked
                        ORDER BY rank_in_group, article_id, source_type
                        LIMIT $1
                        FOR UPDATE
                    )
                    UPDATE collections.cards
                    SET status = 'published', published_at = NOW(), updated_at = NOW()
                    WHERE card_id IN (SELECT card_id FROM diverse_pending)
                    RETURNING *
                    """,
                    count,
                )

            published = [self._row_to_card(row) for row in rows]

            # Log unenriched cards that were skipped by the enrichment gate
            target_col = collection_id
            if not target_col:
                target_col = await conn.fetchval(
                    "SELECT collection_id FROM collections.collections WHERE featured = TRUE"
                )
            if target_col:
                unenriched = await conn.fetchval(
                    """
                    SELECT count(*) FROM collections.cards c
                    WHERE c.collection_id = $1 AND c.status = 'pending'
                      AND (c.image_url IS NULL OR c.image_url = ''
                           OR NOT EXISTS (
                               SELECT 1 FROM collections.card_summaries cs
                                WHERE cs.card_id = c.card_id
                                  AND cs.summary_type = 'open_weights'
                           ))
                    """,
                    target_col,
                )
                if unenriched:
                    logger.info(
                        f"Enrichment gate: {unenriched} pending cards skipped "
                        f"(missing image or summaries)"
                    )

            # Auto-activate collection on first publish
            # Collections start as 'draft' and must be 'active' to appear
            # in sync_collections_index_to_kv() which filters WHERE status = 'active'
            if published:
                col_ids = {card.collection_id for card in published}
                for cid in col_ids:
                    await conn.execute(
                        """
                        UPDATE collections.collections
                        SET status = 'active', updated_at = NOW()
                        WHERE collection_id = $1 AND status = 'draft'
                        """,
                        cid,
                    )

            logger.info(f"Published {len(published)} cards (diversity-aware)")
            return published

    async def publish_cards_by_ids(self, card_ids: list[str]) -> list[Card]:
        """Publish specific cards by ID.

        Only publishes cards that are currently 'pending'. Auto-activates
        the collection on first publish (same as publish_cards).

        Args:
            card_ids: Explicit list of card IDs to publish

        Returns:
            List of newly published cards
        """
        if not card_ids:
            return []

        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                UPDATE collections.cards
                SET status = 'published', published_at = NOW(), updated_at = NOW()
                WHERE card_id = ANY($1) AND status = 'pending'
                RETURNING *
                """,
                card_ids,
            )

            published = [self._row_to_card(row) for row in rows]

            # Auto-activate collection on first publish
            if published:
                col_ids = {card.collection_id for card in published}
                for cid in col_ids:
                    await conn.execute(
                        """
                        UPDATE collections.collections
                        SET status = 'active', updated_at = NOW()
                        WHERE collection_id = $1 AND status = 'draft'
                        """,
                        cid,
                    )

            logger.info(f"Published {len(published)} cards by explicit IDs")
            return published

    async def enrich_pending_cards(
        self,
        limit: int = 6,
        collection_id: str | None = None,
    ) -> dict[str, Any]:
        """Enrich unenriched pending cards (summaries + images).

        Finds pending cards that are missing summaries or images and
        enriches them so they become eligible for publish_cards().

        This is the autonomous enrichment path — called by the pg_cron
        publish handler to ensure cards don't stay unenriched forever.

        Args:
            limit: Max cards to enrich per invocation (default: 6)
            collection_id: Collection to target (default: featured)

        Returns:
            Dict with enriched_count, failed_count, and details
        """
        async with self._pool.acquire() as conn:
            # Resolve collection
            col_id = collection_id
            if not col_id:
                col_id = await conn.fetchval(
                    "SELECT collection_id FROM collections.collections WHERE featured = TRUE"
                )
            if not col_id:
                return {"enriched_count": 0, "failed_count": 0, "error": "no_collection"}

            # Find unenriched pending cards
            rows = await conn.fetch(
                """
                SELECT c.card_id, c.title,
                       c.image_url IS NOT NULL AND c.image_url != '' AS has_image,
                       (SELECT count(*) FROM collections.card_summaries cs
                        WHERE cs.card_id = c.card_id) AS summary_count
                FROM collections.cards c
                WHERE c.collection_id = $1 AND c.status = 'pending'
                  AND (c.image_url IS NULL OR c.image_url = ''
                       OR NOT EXISTS (
                           SELECT 1 FROM collections.card_summaries cs
                            WHERE cs.card_id = c.card_id
                              AND cs.summary_type = 'open_weights'
                       ))
                ORDER BY c.created_at ASC
                LIMIT $2
                """,
                col_id, limit,
            )

        if not rows:
            return {"enriched_count": 0, "failed_count": 0, "message": "all_cards_enriched"}

        logger.info(f"Enriching {len(rows)} unenriched pending cards")

        enriched = 0
        failed = 0
        details: list[dict[str, Any]] = []

        for row in rows:
            card_id = row["card_id"]
            has_image = row["has_image"]
            summary_count = row["summary_count"]
            card_failed = False

            # --- Summaries (skip types already generated) ---
            existing_types: set[str] = set()
            if summary_count > 0:
                async with self._pool.acquire() as conn:
                    existing = await conn.fetch(
                        "SELECT summary_type FROM collections.card_summaries WHERE card_id = $1",
                        card_id,
                    )
                    existing_types = {r["summary_type"] for r in existing}

            # Local open-weights is mandatory. Brave/Cerebras vary with
            # API availability and budget — try them, never fail the card
            # if they are down, never skip trying.
            for summary_type in (REQUIRED_CARD_SUMMARY, *OPTIONAL_CARD_SUMMARIES):
                if summary_type in existing_types:
                    continue
                try:
                    await self.generate_card_summary(card_id, summary_type)
                    existing_types.add(summary_type)
                    logger.info(f"Enrich {card_id[:12]}: {summary_type} OK")
                except Exception as e:
                    logger.warning(f"Enrich {card_id[:12]}: {summary_type} FAILED - {e}")
                    details.append({"card_id": card_id, "step": summary_type, "error": str(e)})
                    if summary_type in OPTIONAL_CARD_SUMMARIES:
                        continue
                    card_failed = True
                    break

            if card_failed:
                failed += 1
                continue

            # --- Image rendering via gRPC ---
            if not has_image:
                try:
                    await self._enrich_render_card(card_id)
                    logger.info(f"Enrich {card_id[:12]}: render OK")
                except Exception as e:
                    logger.warning(f"Enrich {card_id[:12]}: render FAILED - {e}")
                    details.append({"card_id": card_id, "step": "render", "error": str(e)})
                    failed += 1
                    continue

            # --- Sync card page to KV ---
            try:
                await self.sync_card_to_kv(card_id)
            except Exception as e:
                logger.warning(f"Enrich {card_id[:12]}: KV sync failed (non-fatal) - {e}")

            enriched += 1

        logger.info(f"Enrichment complete: {enriched} enriched, {failed} failed")
        return {
            "enriched_count": enriched,
            "failed_count": failed,
            "details": details,
        }

    async def _enrich_render_card(self, card_id: str) -> None:
        """Render a single card's image via gRPC RenderCards.

        Uses the gRPC client (same as the curation flow) so rendering
        goes through proper GPU workload management.

        Args:
            card_id: Card to render

        Raises:
            RuntimeError: If rendering fails
        """
        from gaius.client.grpc_client import get_grpc_client, GrpcClientConfig

        client = await get_grpc_client(GrpcClientConfig.for_cli())

        async for event in client.RenderCards(
            card_id=card_id,
            upload=True,
        ):
            if event.error:
                raise RuntimeError(f"Render error: {event.error}")

    async def get_cards_for_kv(self, limit: int = 200) -> list[dict[str, Any]]:
        """Get all published cards across active collections for Cloudflare KV.

        Returns cards from ALL active collections as public dicts,
        sorted by published_at descending — ready for JSON serialization
        and the landing page published_cards KV key.
        """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT c.* FROM collections.cards c
                JOIN collections.collections col ON c.collection_id = col.collection_id
                WHERE col.status = 'active' AND c.status = 'published'
                ORDER BY c.published_at DESC
                LIMIT $1
                """,
                limit,
            )
        return [self._row_to_card(row).to_public_dict() for row in rows]

    # =========================================================================
    # Statistics
    # =========================================================================

    async def get_stats(self, collection_id: str | None = None) -> dict[str, Any]:
        """Get collection statistics.

        Args:
            collection_id: Specific collection (or all if None)

        Returns:
            Statistics dict
        """
        async with self._pool.acquire() as conn:
            if collection_id:
                row = await conn.fetchrow(
                    """
                    SELECT
                        (SELECT COUNT(*) FROM collections.cards WHERE collection_id = $1) as total_cards,
                        (SELECT COUNT(*) FROM collections.cards WHERE collection_id = $1 AND status = 'pending') as pending_cards,
                        (SELECT COUNT(*) FROM collections.cards WHERE collection_id = $1 AND status = 'published') as published_cards,
                        (SELECT COUNT(*) FROM collections.sources s JOIN collections.cards c ON s.card_id = c.card_id WHERE c.collection_id = $1) as total_sources
                    """,
                    collection_id,
                )
            else:
                row = await conn.fetchrow(
                    """
                    SELECT
                        (SELECT COUNT(*) FROM collections.collections) as total_collections,
                        (SELECT COUNT(*) FROM collections.collections WHERE featured = TRUE) as featured_count,
                        (SELECT COUNT(*) FROM collections.cards) as total_cards,
                        (SELECT COUNT(*) FROM collections.cards WHERE status = 'pending') as pending_cards,
                        (SELECT COUNT(*) FROM collections.cards WHERE status = 'published') as published_cards
                    """
                )

            return dict(row) if row else {}

    # =========================================================================
    # Cloudflare KV Sync
    # =========================================================================

    def _get_kv_credentials(self) -> tuple[str, str, str]:
        """Get Cloudflare KV credentials from environment.

        Returns:
            Tuple of (account_id, api_token, namespace_id)

        Raises:
            CollectionError: If credentials not configured
        """
        # Get KV config from HOCON config (env vars resolved at config-load time)
        # Use CLOUDFLARE_COLLECTIONS_KV_NAMESPACE_ID for collections (GAIUS_COLLECTIONS namespace)
        # This is distinct from CLOUDFLARE_KV_NAMESPACE_ID which is used for sessions (GAIUS_SESSIONS)
        from gaius.core.config import get_config

        cf_cfg = get_config().cloudflare
        account_id = cf_cfg.account_id or self._config.cf_account_id
        api_token = cf_cfg.api_token or self._config.cf_api_token
        namespace_id = os.environ.get(
            "CLOUDFLARE_COLLECTIONS_KV_NAMESPACE_ID",
            os.environ.get("CLOUDFLARE_KV_NAMESPACE_ID", self._config.cf_kv_namespace_id)
        )

        if not all([account_id, api_token, namespace_id]):
            raise CollectionError(
                "Cloudflare KV not configured.\n"
                "  Set: CLOUDFLARE_ACCOUNT_ID, CLOUDFLARE_API_TOKEN, CLOUDFLARE_COLLECTIONS_KV_NAMESPACE_ID\n"
                "  Or configure via CollectionConfig",
                guru_code="#COL.00000003.KVFAIL",
            )

        return account_id, api_token, namespace_id

    async def sync_theme_config(self) -> dict[str, Any]:
        """Sync theme configuration from HOCON to Cloudflare KV.

        Reads landing page settings from base.conf and pushes
        the theme_config to KV for the Cloudflare Worker to use.

        Returns:
            Result dict with success status and theme synced
        """
        import aiohttp
        import json

        try:
            from pyhocon import ConfigFactory
        except ImportError:
            raise CollectionError(
                "pyhocon not installed. Run: uv add pyhocon",
                guru_code="#COL.00000006.CONFIGFAIL",
            )

        # Load HOCON config
        config_path = os.path.join(
            os.path.dirname(__file__), "..", "..", "..", "..", "config", "base.conf"
        )
        try:
            config = ConfigFactory.parse_file(config_path)
        except Exception as e:
            raise CollectionError(
                f"Failed to load config: {e}",
                guru_code="#COL.00000006.CONFIGFAIL",
            ) from e

        # Extract landing page config
        landing = config.get("gaius.landing", {})
        theme_config = {
            "theme_id": landing.get("theme_id", "keiretsu-dark"),
            "title": landing.get("title", "Gaius"),
            "subtitle": landing.get("subtitle", "Curated research in AI reasoning, epistemic uncertainty, and normative aesthetics"),
        }

        # Get KV credentials
        account_id, api_token, namespace_id = self._get_kv_credentials()

        # Push to KV
        url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/storage/kv/namespaces/{namespace_id}/values/theme_config"

        headers = {
            "Authorization": f"Bearer {api_token}",
            "Content-Type": "application/json",
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.put(
                    url,
                    headers=headers,
                    data=json.dumps(theme_config),
                ) as resp:
                    if resp.status != 200:
                        error_text = await resp.text()
                        raise CollectionError(
                            f"Cloudflare KV API error: {resp.status} - {error_text}",
                            guru_code="#COL.00000003.KVFAIL",
                        )

            logger.info(f"Synced theme config to Cloudflare KV: {theme_config['theme_id']}")
            return {
                "success": True,
                "theme_id": theme_config["theme_id"],
                "title": theme_config["title"],
                "namespace_id": namespace_id,
            }

        except aiohttp.ClientError as e:
            raise CollectionError(
                f"Cloudflare KV network error: {e}",
                guru_code="#COL.00000003.KVFAIL",
            ) from e

    async def sync_to_kv(self) -> dict[str, Any]:
        """Sync published cards to Cloudflare KV.

        Pushes all published cards to the GAIUS_COLLECTIONS KV namespace
        using the Cloudflare REST API.

        Returns:
            Result dict with success status and cards synced
        """
        import aiohttp
        import json

        account_id, api_token, namespace_id = self._get_kv_credentials()

        # Get cards for KV
        cards = await self.get_cards_for_kv()

        # Cloudflare KV API endpoint
        url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/storage/kv/namespaces/{namespace_id}/values/published_cards"

        headers = {
            "Authorization": f"Bearer {api_token}",
            "Content-Type": "application/json",
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.put(
                    url,
                    headers=headers,
                    data=json.dumps(cards),
                ) as resp:
                    if resp.status != 200:
                        error_text = await resp.text()
                        raise CollectionError(
                            f"Cloudflare KV API error: {resp.status} - {error_text}",
                            guru_code="#COL.00000003.KVFAIL",
                        )

            logger.info(f"Synced {len(cards)} cards to Cloudflare KV")
            return {
                "success": True,
                "cards_synced": len(cards),
                "namespace_id": namespace_id,
            }

        except aiohttp.ClientError as e:
            raise CollectionError(
                f"Cloudflare KV network error: {e}",
                guru_code="#COL.00000003.KVFAIL",
            ) from e

    async def publish_and_sync(
        self,
        count: int = 3,
        collection_id: str | None = None,
    ) -> dict[str, Any]:
        """Publish cards and sync to Cloudflare KV.

        Convenience method that combines publish_cards() and sync_to_kv().

        Args:
            count: Number of cards to publish
            collection_id: Optional specific collection

        Returns:
            Result with published cards and sync status
        """
        # Publish cards first
        published = await self.publish_cards(count=count, collection_id=collection_id)

        # Sync individual card detail pages to KV. One immediate retry
        # per card absorbs transient Cloudflare errors; a persistent
        # failure is recorded honestly and surfaced by the caller
        # (#COL.00000017.CARDKVFAIL) — never discarded.
        card_sync_results = []
        for card in published:
            last_err: Exception | None = None
            for attempt in (1, 2):
                try:
                    await self.sync_card_to_kv(card.card_id)
                    card_sync_results.append(
                        {"card_id": card.card_id, "success": True}
                    )
                    last_err = None
                    break
                except Exception as e:
                    last_err = e
                    logger.warning(
                        f"Card KV sync attempt {attempt}/2 failed for "
                        f"{card.card_id}: {e}"
                    )
            if last_err is not None:
                card_sync_results.append(
                    {
                        "card_id": card.card_id,
                        "success": False,
                        "error": str(last_err),
                    }
                )

        # Sync landing page card list to KV
        sync_result = await self.sync_to_kv()

        return {
            "published": [card.to_public_dict() for card in published],
            "published_count": len(published),
            "card_syncs": card_sync_results,
            "kv_sync": sync_result,
        }

    # =========================================================================
    # Article Situational Awareness
    # =========================================================================

    async def get_article_status(self) -> dict[str, Any]:
        """Get article curation situational awareness.

        Returns status suitable for /article sitrep display:
        - running: Is an article curation flow currently executing?
        - current_run_id: UUID of running flow (if any)
        - current_step: Current step name (if running)
        - articles_pending: Count of pending articles
        - articles_list: List of articles with slug, title, zk_count, status
        - recent_curations: List of recent completed curations
        - total_cards_pending: Count of pending cards
        - total_cards_published: Count of published cards
        """
        async with self._pool.acquire() as conn:
            # Check for running flow via progress table
            running_row = await conn.fetchrow(
                """
                SELECT run_id, step, message, created_at
                FROM meta.article_curation_progress
                WHERE step NOT IN ('complete', 'failed')
                ORDER BY created_at DESC
                LIMIT 1
                """
            )

            running = running_row is not None
            current_run_id = running_row["run_id"] if running_row else None
            current_step = running_row["step"] if running_row else None

            # Get articles list from database
            articles_rows = await conn.fetch(
                """
                SELECT slug, title, status, zk_count, sources_count
                FROM collections.articles
                ORDER BY
                    CASE WHEN status = 'pending' THEN 0
                         WHEN status = 'researching' THEN 1
                         WHEN status = 'drafting' THEN 2
                         ELSE 3
                    END,
                    created_at DESC
                LIMIT 20
                """
            )
            articles_list = [
                {
                    "slug": row["slug"],
                    "title": row["title"],
                    "status": row["status"],
                    "zk_count": row["zk_count"] or 0,
                    "sources_count": row["sources_count"] or 0,
                }
                for row in articles_rows
            ]

            # Count pending articles
            articles_pending = await conn.fetchval(
                """
                SELECT COUNT(*) FROM collections.articles
                WHERE status IN ('pending', 'researching', 'drafting')
                """
            ) or 0

            # Get recent curations
            recent_rows = await conn.fetch(
                """
                SELECT DISTINCT ON (run_id)
                    run_id,
                    metadata->>'slug' as slug,
                    created_at,
                    metadata->>'cards_created' as cards_created
                FROM meta.article_curation_progress
                WHERE step = 'complete'
                ORDER BY run_id, created_at DESC
                LIMIT 5
                """
            )
            recent_curations = [
                {
                    "run_id": row["run_id"],
                    "slug": row["slug"] or "unknown",
                    "completed_at": row["created_at"].isoformat() if row["created_at"] else None,
                    "cards_created": int(row["cards_created"]) if row["cards_created"] else 0,
                }
                for row in recent_rows
            ]

            # Card counts
            cards_pending = await conn.fetchval(
                "SELECT COUNT(*) FROM collections.cards WHERE status = 'pending'"
            ) or 0
            cards_published = await conn.fetchval(
                "SELECT COUNT(*) FROM collections.cards WHERE status = 'published'"
            ) or 0

            return {
                "running": running,
                "current_run_id": current_run_id,
                "current_step": current_step,
                "articles_pending": articles_pending,
                "articles_list": articles_list,
                "recent_curations": recent_curations,
                "total_cards_pending": cards_pending,
                "total_cards_published": cards_published,
            }

    # =========================================================================
    # Article Creation (Engine-First)
    # =========================================================================

    async def create_article(
        self,
        slug: str,
        title: str = "",
    ) -> dict[str, Any]:
        """Create new article directory structure.

        Engine owns KB filesystem - clients MUST NOT write directly.
        This method creates the KB directory structure AND the database record.

        Args:
            slug: URL-friendly identifier (will be date-prefixed as YYYYMMDD-slug)
            title: Display title (defaults to title-cased slug without date prefix)

        Returns:
            Dict with slug, title, kb_path, article_id, collection_id

        Raises:
            CollectionError: If article already exists or creation fails
        """
        from pathlib import Path
        import yaml
        import re
        from datetime import datetime

        # Generate date prefix (YYYYMMDD format)
        now = datetime.now()
        date_prefix = now.strftime("%Y%m%d")

        # Check if slug already has a date prefix (avoid double-prefixing)
        if re.match(r'^\d{8}-', slug):
            final_slug = slug
            # Use the part after the date for title generation
            title_source = slug[9:]  # Skip "YYYYMMDD-"
        else:
            final_slug = f"{date_prefix}-{slug}"
            title_source = slug

        # Use original slug (without date) for title if not provided
        if not title:
            title = title_source.replace("-", " ").title()

        kb_root = Path(self._config.kb_root)
        article_dir = kb_root / "current" / "articles" / final_slug
        kb_path = f"current/articles/{final_slug}"

        if article_dir.exists():
            raise CollectionError(
                f"Article directory already exists: {article_dir}",
                guru_code="#COL.00000008.DUPLICATE",
            )

        try:
            # Create directory structure
            article_dir.mkdir(parents=True, exist_ok=True)
            (article_dir / "zk").mkdir(exist_ok=True)
            (article_dir / "hx").mkdir(exist_ok=True)
            (article_dir / "sources").mkdir(exist_ok=True)

            # Create article.md with frontmatter
            now = datetime.now()
            frontmatter = {
                "title": title,
                "status": "pending",
                "version": 0,
                "created_at": now.isoformat(),
                "updated_at": now.isoformat(),
                "arxiv_categories": [],
                "keywords": [],
                "news_queries": [],
            }
            yaml_str = yaml.dump(frontmatter, default_flow_style=False, allow_unicode=True)
            article_content = f"""---
{yaml_str.strip()}
---

# {title}

<!-- Article draft will be generated by the curation pipeline -->
"""
            (article_dir / "article.md").write_text(article_content)

            # Create initial zettelkasten note
            zk_time = now.strftime("%H%M%S")
            zk_note = f"""---
type: research-seed
title: "Initial research direction for {title}"
created_at: {now.isoformat()}
---

# Research Seed: {title}

## Research Questions

- What is the core thesis of this article?
- What evidence and sources support it?
- Who is the target audience?

## Keywords

- Add keywords here for research phase

## Related KB Content

- Link to relevant KB documents here
"""
            (article_dir / "zk" / f"{zk_time}_research_seed.md").write_text(zk_note)

            # Create database record with 1:1 collection
            article, collection = await self.create_article_with_collection(
                slug=final_slug,
                title=title,
                kb_path=kb_path,
            )

            logger.info(f"Created article '{final_slug}' at {article_dir}")

            return {
                "slug": final_slug,
                "title": title,
                "kb_path": str(article_dir),
                "article_id": article.article_id,
                "collection_id": collection.collection_id,
                "message": f"Created article '{title}' at {article_dir}. Add research notes to zk/ then run /article curate {final_slug}",
            }

        except CollectionError:
            # Re-raise CollectionError as-is
            raise
        except Exception as e:
            # Cleanup on failure
            if article_dir.exists():
                import shutil
                shutil.rmtree(article_dir, ignore_errors=True)
            raise CollectionError(
                f"Failed to create article: {e}",
                guru_code="#COL.00000007.ARTICLEFAIL",
            ) from e

    # =========================================================================
    # Article Curation Streaming
    # =========================================================================

    async def article_curate_stream(
        self,
        slug: str = "",
    ) -> AsyncIterator[ArticleCurationEvent]:
        """Stream article curation progress via pg_notify.

        Starts ArticleCurationFlow in the background and streams progress
        events via PostgreSQL LISTEN/NOTIFY. Events include:
        - start: Flow started
        - select: Article selected
        - research: Zettelkasten synthesis
        - acquire: External source acquisition
        - summarize: LLM summarization
        - draft: Draft generation
        - base: .base file creation
        - cards: Card creation
        - complete: Flow completed
        - failed: Flow failed

        Args:
            slug: Optional article slug to curate (if empty, selects from pending)

        Yields:
            ArticleCurationEvent objects as they occur
        """
        import asyncio
        import json
        import subprocess

        # Create a queue for events from pg_notify
        event_queue: asyncio.Queue[ArticleCurationEvent | None] = asyncio.Queue()
        run_id: str | None = None

        # Capture the running loop for use in callbacks
        loop = asyncio.get_running_loop()

        def on_notification(
            conn: asyncpg.Connection,
            pid: int,
            channel: str,
            payload: str,
        ) -> None:
            """Handle pg_notify callback (sync, from asyncpg).

            asyncpg callbacks run synchronously on the event loop thread,
            so we can directly put to the queue without call_soon_threadsafe.
            """
            nonlocal run_id
            try:
                event = ArticleCurationEvent.from_payload(payload)
                logger.debug(f"pg_notify received: {event.step} - {event.message[:50]}")

                # Track the run_id from the first event
                if run_id is None:
                    run_id = event.run_id
                    logger.info(f"Tracking article curation run: {run_id}")

                # Only process events for our run
                if run_id and event.run_id == run_id:
                    # asyncpg callbacks are on the same thread as the event loop,
                    # so we can put directly to the queue
                    event_queue.put_nowait(event)
            except (json.JSONDecodeError, KeyError) as e:
                logger.warning(f"Failed to parse article curation event: {e}")

        # Get a dedicated connection for LISTEN
        from gaius.core.config import get_database_url

        db_url = get_database_url()

        conn: asyncpg.Connection | None = None
        flow_task: asyncio.Task | None = None

        try:
            # Connect and start listening
            conn = await asyncpg.connect(db_url)
            await conn.add_listener("article_curation_progress", on_notification)
            logger.info("Listening on article_curation_progress channel")

            # Start the flow in a background task
            async def run_flow():
                """Run ArticleCurationFlow via subprocess."""
                # Brief delay to ensure pg_notify listener is fully active
                await asyncio.sleep(0.1)

                try:
                    import time

                    from gaius.engine.flow_processes import (
                        SpawnedFlow,
                        flow_processes,
                    )
                    from gaius.engine.sentinel_claim import (
                        YkAdmitError,
                        apply_and_admit,
                        bind_workload_id,
                        delete_flow_sentinel,
                    )
                    from gaius.flows.config import metaflow_child_env

                    wid = ""
                    cmd = [
                        "uv", "run", "--no-sync", "python", "-m", "gaius.flows.article_curation.flow",
                        "run",
                    ]
                    if slug:
                        cmd.extend(["--article", slug])

                    wid = bind_workload_id(
                        "article-curate", f"article-curate-{int(time.time())}"
                    )
                    try:
                        await asyncio.to_thread(apply_and_admit, wid, "article-curate")  # off-loop
                    except YkAdmitError as e:
                        logger.error("article curate YK admit failed: %s", e)
                        raise

                    logger.info(f"Starting article curation: {' '.join(cmd)} workload_id={wid}")

                    env = metaflow_child_env()
                    env["GAIUS_KB_ROOT"] = self._config.kb_root
                    env["GAIUS_YK_APPLICATION_ID"] = wid

                    process = await asyncio.create_subprocess_exec(
                        *cmd,
                        cwd=os.environ.get("GAIUS_PROJECT_ROOT", os.getcwd()),
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                        env=env,
                    )
                    flow_processes().register(
                        SpawnedFlow(
                            workload_id=wid,
                            kind="article-curate",
                            proc=process,
                        )
                    )

                    stdout, stderr = await process.communicate()

                    if process.returncode != 0:
                        logger.error(f"ArticleCurationFlow failed: {stderr.decode()}")
                        # Emit a failed event if we tracked a run_id
                        if run_id:
                            failed_event = ArticleCurationEvent(
                                event_id=0,
                                run_id=run_id,
                                step="failed",
                                step_number=-1,
                                total_steps=9,
                                progress=-1.0,
                                message=f"Flow failed: {stderr.decode()[:200]}",
                                metadata={"exit_code": process.returncode},
                            )
                            await event_queue.put(failed_event)
                    else:
                        logger.info("ArticleCurationFlow completed successfully")

                except Exception as e:
                    logger.error(f"Failed to run ArticleCurationFlow: {e}")
                    if run_id:
                        failed_event = ArticleCurationEvent(
                            event_id=0,
                            run_id=run_id,
                            step="failed",
                            step_number=-1,
                            total_steps=9,
                            progress=-1.0,
                            message=f"Flow error: {str(e)[:200]}",
                            metadata={},
                        )
                        await event_queue.put(failed_event)

                finally:
                    # Keep the YK Application until the host child is gone
                    # (Yield or natural end). A cancelled CLI stream must not
                    # kubectl-delete the claim — that 404s extract mid-run.
                    proc = None
                    try:
                        row = flow_processes().get(wid) if wid else None
                        proc = row.proc if row else None
                    except Exception:
                        pass
                    still_running = proc is not None and proc.returncode is None
                    if still_running:
                        logger.info(
                            "leaving Application %s up (host child still running)",
                            wid,
                        )
                    elif wid:
                        flow_processes().unregister(wid)
                        await asyncio.to_thread(delete_flow_sentinel, wid)
                    await event_queue.put(None)

            flow_task = asyncio.create_task(run_flow())

            # Yield events as they come in
            while True:
                try:
                    # Wait for event with timeout
                    event = await asyncio.wait_for(event_queue.get(), timeout=300.0)
                    if event is None:
                        # Flow completed (success or failure)
                        break
                    yield event

                    # Check for terminal states
                    if event.step in ("complete", "failed"):
                        break

                except asyncio.TimeoutError:
                    logger.warning("Article curation stream timeout (5 min)")
                    break

        finally:
            # Cleanup
            if conn:
                try:
                    await conn.remove_listener("article_curation_progress", on_notification)
                    await conn.close()
                except Exception:
                    pass

            if flow_task and not flow_task.done():
                flow_task.cancel()
                try:
                    await flow_task
                except asyncio.CancelledError:
                    pass

    # =========================================================================
    # Collection Summary Generation
    # =========================================================================

    async def generate_collection_summary(
        self,
        collection_id: str,
        summary_type: str = "frontier",
    ) -> dict[str, Any]:
        """Generate an AI summary for a collection.

        Uses the collection's published cards to build a content overview,
        then calls the appropriate LLM backend for summarization.

        Args:
            collection_id: Collection to summarize
            summary_type: "frontier" (xai/grok), "open_weights" (local GPU),
                or "cerebras" (Cerebras GLM-4.7 with thinking trace)

        Returns:
            Dict with summary text, model label, and metadata

        Raises:
            CollectionError: If collection not found or LLM call fails
        """
        import time as _time

        if summary_type not in ("frontier", "open_weights", "cerebras"):
            raise CollectionError(
                f"Invalid summary_type: {summary_type}. Must be 'frontier', 'open_weights', or 'cerebras'.",
                guru_code="#COL.00000009.SUMMARYFAIL",
            )

        # Fetch collection
        collection = await self.get_collection(collection_id)
        if not collection:
            raise CollectionError(
                f"Collection not found: {collection_id}",
                guru_code="#COL.00000001.NOTFOUND",
            )

        # Get published cards for context
        cards = await self.list_cards(collection_id, status="published")
        if not cards:
            # Also try pending cards if none published yet
            cards = await self.list_cards(collection_id, limit=20)

        # Build prompt from collection + cards
        card_descriptions = "\n".join(
            f"- {card.title}: {card.summary} [{card.source_type}]"
            for card in cards[:30]  # Cap at 30 cards for prompt size
        )

        prompt = (
            f"You are summarizing a curated research collection.\n\n"
            f"Collection: {collection.name}\n"
            f"Description: {collection.description}\n\n"
            f"The collection contains {len(cards)} cards covering these topics:\n"
            f"{card_descriptions}\n\n"
            f"Write a substantive 2-3 paragraph summary of what this collection covers, "
            f"the key themes and connections between the research materials, and why "
            f"these topics matter. Write for a technically literate audience. "
            f"Use markdown formatting (paragraphs, bold for emphasis)."
        )

        messages = [{"role": "user", "content": prompt}]

        # Call appropriate backend
        start_ms = int(_time.time() * 1000)

        if summary_type == "frontier":
            from gaius.engine.backends.external.xai_backend import XAIBackend
            backend = XAIBackend()
            if not backend.is_available:
                raise CollectionError(
                    "XAI backend not available (XAI_API_KEY not set).\n"
                    "  Set: XAI_API_KEY environment variable",
                    guru_code="#COL.00000009.SUMMARYFAIL",
                )
            response = await backend.complete(
                messages,
                model="grok-4-1-fast",
                temperature=0.7,
                max_tokens=EXTERNAL_MAX_TOKENS,
            )
            model_label = "frontier model"
        elif summary_type == "open_weights":
            # open_weights — use local engine (Devstral-24B on tinybox GPUs)
            from gaius.client.engine_client import get_engine_client, Message as EngMsg

            engine = await get_engine_client()
            # TECH DEBT: Uses model="thinking" (direct vLLM). Should use model="leader"
            # to route through optillm for prompt optimization.
            result = await engine.complete(
                [EngMsg(role="user", content=prompt)],
                model="thinking",
                temperature=0.7,
                max_tokens=EXTERNAL_MAX_TOKENS,
            )
            # Wrap in ExternalResponse-compatible shape
            from gaius.engine.backends.external.base import ExternalResponse
            response = ExternalResponse(
                content=result.content,
                model=result.model,
                provider=result.backend or "local-engine",
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
            )
            model_label = "open-weights reasoning model"

        else:
            # cerebras — use Cerebras GLM-4.7 via external router
            from gaius.engine.backends.external.router import ExternalInferenceRouter

            router = ExternalInferenceRouter(
                capture_exchanges=self._capture_exchanges_enabled(),
            )
            response = await router.complete(
                messages,
                provider="cerebras",
                temperature=0.7,
                max_tokens=EXTERNAL_MAX_TOKENS,
            )
            model_label = "cerebras thinking"

        latency_ms = int(_time.time() * 1000) - start_ms

        if not response.success:
            raise CollectionError(
                f"LLM generation failed: {response.error}\n"
                f"  Backend: {response.provider}\n"
                f"  Try: /health fix endpoints",
                guru_code="#COL.00000009.SUMMARYFAIL",
            )

        summary_text = response.content
        thinking_trace = response.reasoning

        # Store to Iceberg HX
        hx_generation_id = str(uuid.uuid4())
        await self._store_generation_to_hx(
            generation_id=hx_generation_id,
            collection_id=collection_id,
            summary_type=summary_type,
            prompt=prompt,
            output=summary_text,
            thinking_trace=thinking_trace,
            model_name=response.model,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            latency_ms=latency_ms,
        )

        # UPSERT to PostgreSQL
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO collections.collection_summaries
                (collection_id, summary_type, hx_generation_id, summary_text,
                 model_label, input_tokens, output_tokens, generated_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, NOW())
                ON CONFLICT (collection_id, summary_type) DO UPDATE SET
                    hx_generation_id = EXCLUDED.hx_generation_id,
                    summary_text = EXCLUDED.summary_text,
                    model_label = EXCLUDED.model_label,
                    input_tokens = EXCLUDED.input_tokens,
                    output_tokens = EXCLUDED.output_tokens,
                    generated_at = NOW()
                """,
                collection_id, summary_type, hx_generation_id, summary_text,
                model_label, response.input_tokens, response.output_tokens,
            )

        logger.info(
            f"Generated {summary_type} summary for {collection.slug} "
            f"({response.input_tokens}in/{response.output_tokens}out, {latency_ms}ms)"
        )

        return {
            "collection_id": collection_id,
            "summary_type": summary_type,
            "summary_text": summary_text,
            "model_label": model_label,
            "hx_generation_id": hx_generation_id,
            "input_tokens": response.input_tokens,
            "output_tokens": response.output_tokens,
            "latency_ms": latency_ms,
        }

    async def _store_generation_to_hx(
        self,
        generation_id: str,
        collection_id: str,
        summary_type: str,
        prompt: str,
        output: str,
        thinking_trace: str | None,
        model_name: str,
        input_tokens: int,
        output_tokens: int,
        latency_ms: int,
    ) -> None:
        """Store LLM generation to Iceberg HX for provenance.

        Raises:
            CollectionError: If storage fails (fail-fast, no fallback).
        """
        import pyarrow as pa
        from gaius.hx.catalog import get_catalog
        from gaius.hx.tables import get_llm_generation_table

        try:
            catalog = get_catalog()
        except Exception as e:
            raise CollectionError(
                f"Iceberg HX catalog unavailable: {e}\n"
                "  Try: /health fix hx\n"
                "  Or:  Check MinIO + PostgreSQL catalog connectivity",
                guru_code="#HX.00000001.CATALOGFAIL",
            ) from e

        try:
            table = get_llm_generation_table(catalog)
        except Exception as e:
            raise CollectionError(
                f"Failed to access llm.generations table: {e}\n"
                "  Try: /health fix hx\n"
                "  Or:  Ensure 'llm' namespace exists in Iceberg catalog",
                guru_code="#HX.00000002.TABLEFAIL",
            ) from e

        now = datetime.now(timezone.utc)

        # Explicit schema matching Iceberg table: required fields must be non-nullable
        arrow_schema = pa.schema([
            pa.field("id", pa.string(), nullable=False),
            pa.field("collection_id", pa.string(), nullable=True),
            pa.field("summary_type", pa.string(), nullable=False),
            pa.field("prompt", pa.string(), nullable=False),
            pa.field("output", pa.string(), nullable=False),
            pa.field("thinking_trace", pa.string(), nullable=True),
            pa.field("model_name", pa.string(), nullable=False),
            pa.field("input_tokens", pa.int64(), nullable=True),
            pa.field("output_tokens", pa.int64(), nullable=True),
            pa.field("latency_ms", pa.int64(), nullable=True),
            pa.field("generated_at", pa.timestamp("us", tz="UTC"), nullable=False),
        ])

        record = pa.table({
            "id": [generation_id],
            "collection_id": [collection_id],
            "summary_type": [summary_type],
            "prompt": [prompt],
            "output": [output],
            "thinking_trace": [thinking_trace or ""],
            "model_name": [model_name],
            "input_tokens": [input_tokens],
            "output_tokens": [output_tokens],
            "latency_ms": [latency_ms],
            "generated_at": [now],
        }, schema=arrow_schema)

        try:
            table.append(record)
        except Exception as e:
            raise CollectionError(
                f"Failed to write generation to Iceberg HX: {e}\n"
                "  Try: /health fix hx\n"
                "  Or:  Check MinIO storage availability",
                guru_code="#HX.00000003.WRITEFAIL",
            ) from e

        logger.debug(f"Stored generation {generation_id} to Iceberg HX")

    # =========================================================================
    # Card Summary Generation
    # =========================================================================

    async def generate_card_summary(
        self,
        card_id: str,
        summary_type: str = "frontier",
    ) -> dict[str, Any]:
        """Generate an AI summary for an individual card page.

        For frontier type: Uses Brave Summarizer (grounded in web results).
        For open_weights type: Uses local GPU engine (Devstral-24B).
        For cerebras type: Uses Cerebras GLM-4.7 with thinking trace for HX.

        Args:
            card_id: Card to summarize
            summary_type: "frontier" (brave), "open_weights" (local GPU),
                or "cerebras" (Cerebras GLM-4.7 with thinking trace)

        Returns:
            Dict with summary text, model label, and metadata

        Raises:
            CollectionError: If card not found or generation fails
        """
        import time as _time

        if summary_type not in ("frontier", "open_weights", "cerebras"):
            raise CollectionError(
                f"Invalid summary_type: {summary_type}. Must be 'frontier', 'open_weights', or 'cerebras'.",
                guru_code="#COL.00000013.CARDSUMFAIL",
            )

        # Fetch card
        card = await self.get_card(card_id)
        if not card:
            raise CollectionError(
                f"Card not found: {card_id}",
                guru_code="#COL.00000001.NOTFOUND",
            )

        start_ms = int(_time.time() * 1000)
        brave_followups: list[str] = []

        if summary_type == "frontier":
            # Use Brave Answers API for grounded, web-cited summaries
            # Retry with exponential backoff — Brave rate-limits sequential calls
            from gaius.search.brave import BraveSearch
            max_attempts = 3
            result = None  # type: ignore[assignment]  # set in retry loop or raise
            last_error: Exception | None = None
            for attempt in range(max_attempts):
                try:
                    async with BraveSearch("unused", capture_exchanges=self._capture_exchanges_enabled()) as brave:
                        result = await brave.summarize_topic(card.title, card.summary)
                    last_error = None
                    break
                except Exception as e:
                    last_error = e
                    if attempt < max_attempts - 1:
                        backoff = 2 ** (attempt + 1)  # 2s, 4s
                        logger.warning(
                            f"Brave summarize attempt {attempt + 1}/{max_attempts} failed for "
                            f"{card.title[:50]}: {e}. Retrying in {backoff}s..."
                        )
                        await asyncio.sleep(backoff)
            if last_error is not None:
                raise CollectionError(
                    f"Brave Summarizer failed after {max_attempts} attempts: {last_error}\n"
                    f"  Card: {card.title[:60]}\n"
                    f"  Try: Wait and retry, or check Brave API quota",
                    guru_code="#COL.00000014.BRAVERETRYFAIL",
                )
            summary_text = result.summary_text
            model_label = "brave answers"
            input_tokens = result.input_tokens
            output_tokens = result.output_tokens
            provider = "brave-answers"
            thinking_trace = None
            # Store unique citation URLs for display on card page
            seen_urls: set[str] = set()
            for cite in result.citations:
                if cite.url and cite.url not in seen_urls:
                    seen_urls.add(cite.url)
                    brave_followups.append(cite.url)
        elif summary_type == "open_weights":
            # open_weights — use local engine (Devstral-24B on tinybox GPUs)
            from gaius.client.engine_client import get_engine_client, Message

            engine = await get_engine_client()

            prompt = (
                f"You are summarizing a research material for a curated collection.\n\n"
                f"Title: {card.title}\n"
                f"Brief: {card.summary}\n"
                f"Source type: {card.source_type}\n"
                f"Source URL: {card.source_url}\n\n"
                f"Write a substantive 2-3 paragraph summary explaining what this material "
                f"covers, its key contributions or insights, and why it matters. "
                f"Write for a technically literate audience. Use markdown formatting."
            )

            # TECH DEBT: Uses model="thinking" (direct vLLM). Should use model="leader"
            # to route through optillm for prompt optimization.
            result = await engine.complete(
                [Message(role="user", content=prompt)],
                model="thinking",
                temperature=0.7,
                max_tokens=REASONING_MAX_TOKENS,
            )

            if not result.content:
                raise CollectionError(
                    f"Local engine generation returned empty content.\n"
                    f"  Model: {result.model}\n"
                    f"  Try: /health fix endpoints",
                    guru_code="#COL.00000013.CARDSUMFAIL",
                )

            summary_text = result.content
            model_label = "open-weights reasoning model"
            input_tokens = result.input_tokens
            output_tokens = result.output_tokens
            provider = result.backend or "local-engine"
            thinking_trace = None

        else:
            # cerebras — use Cerebras GLM-4.7 via external router
            from gaius.engine.backends.external.router import ExternalInferenceRouter

            router = ExternalInferenceRouter(
                capture_exchanges=self._capture_exchanges_enabled(),
            )

            prompt = (
                f"You are summarizing a research material for a curated collection.\n\n"
                f"Title: {card.title}\n"
                f"Brief: {card.summary}\n"
                f"Source type: {card.source_type}\n"
                f"Source URL: {card.source_url}\n\n"
                f"Write a substantive 2-3 paragraph summary explaining what this material "
                f"covers, its key contributions or insights, and why it matters. "
                f"Write for a technically literate audience. Use markdown formatting."
            )

            response = await router.complete(
                [{"role": "user", "content": prompt}],
                provider="cerebras",
                temperature=0.7,
                max_tokens=EXTERNAL_MAX_TOKENS,
            )

            if not response.success:
                raise CollectionError(
                    f"Cerebras generation failed: {response.error}\n"
                    f"  Provider: {response.provider}\n"
                    f"  Try: /health fix endpoints",
                    guru_code="#COL.00000013.CARDSUMFAIL",
                )

            summary_text = response.content
            model_label = "cerebras thinking"
            input_tokens = response.input_tokens
            output_tokens = response.output_tokens
            provider = response.provider
            thinking_trace = response.reasoning

        latency_ms = int(_time.time() * 1000) - start_ms

        hx_generation_id = str(uuid.uuid4())
        # Public landing needs card_summaries even if Iceberg HX is
        # unreachable (stale catalog / wrong S3 endpoint). HX is lineage.
        try:
            await self._store_generation_to_hx(
                generation_id=hx_generation_id,
                collection_id=card.collection_id,
                summary_type=f"card_{summary_type}",
                prompt=f"Card: {card.title} ({card.source_type})",
                output=summary_text,
                thinking_trace=thinking_trace,
                model_name=provider or model_label,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                latency_ms=latency_ms,
            )
        except Exception as e:
            logger.error(
                "HX store failed for %s %s (summary still saved): %s",
                card_id,
                summary_type,
                e,
            )

        # Flag frontier summaries with zero citations for future retry
        needs_retry = summary_type == "frontier" and len(brave_followups) == 0

        # UPSERT to PostgreSQL
        import json as _json
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO collections.card_summaries
                (card_id, summary_type, hx_generation_id, summary_text,
                 model_label, brave_followups, input_tokens, output_tokens,
                 needs_retry, generated_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, NOW())
                ON CONFLICT (card_id, summary_type) DO UPDATE SET
                    hx_generation_id = EXCLUDED.hx_generation_id,
                    summary_text = EXCLUDED.summary_text,
                    model_label = EXCLUDED.model_label,
                    brave_followups = EXCLUDED.brave_followups,
                    input_tokens = EXCLUDED.input_tokens,
                    output_tokens = EXCLUDED.output_tokens,
                    needs_retry = EXCLUDED.needs_retry,
                    generated_at = NOW()
                """,
                card_id, summary_type, hx_generation_id, summary_text,
                model_label,
                _json.dumps(brave_followups) if brave_followups else None,
                input_tokens, output_tokens,
                needs_retry,
            )

        logger.info(
            f"Generated {summary_type} card summary for {card.title[:50]} "
            f"({input_tokens}in/{output_tokens}out, {latency_ms}ms)"
        )

        return {
            "card_id": card_id,
            "summary_type": summary_type,
            "summary_text": summary_text,
            "model_label": model_label,
            "brave_followups": brave_followups,
            "hx_generation_id": hx_generation_id,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "latency_ms": latency_ms,
        }

    @staticmethod
    def _capture_exchanges_enabled() -> bool:
        """Check if exchange capture is enabled."""
        env_val = os.environ.get("GAIUS_HX_CAPTURE_EXCHANGES", "true")
        return env_val.lower() in ("1", "true", "yes")

    # =========================================================================
    # Card Page KV Sync
    # =========================================================================

    async def sync_card_to_kv(
        self,
        card_id: str,
    ) -> dict[str, Any]:
        """Sync a single card's page data to Cloudflare KV.

        Assembles card metadata, summaries (frontier/open_weights/cerebras), brave followups, and
        collection info into a JSON blob for the worker to render.

        Args:
            card_id: Card to sync

        Returns:
            Result dict with sync status

        Raises:
            CollectionError: If card not found or KV push fails
        """
        import aiohttp
        import json

        # Fetch card
        card = await self.get_card(card_id)
        if not card:
            raise CollectionError(
                f"Card not found: {card_id}",
                guru_code="#COL.00000001.NOTFOUND",
            )

        # Fetch collection info
        collection = await self.get_collection(card.collection_id)

        # Fetch summaries
        summaries: dict[str, Any] = {}
        brave_followups: list[str] = []
        async with self._pool.acquire() as conn:
            summary_rows = await conn.fetch(
                """
                SELECT summary_type, summary_text, model_label, brave_followups, generated_at
                FROM collections.card_summaries
                WHERE card_id = $1
                """,
                card_id,
            )
            for row in summary_rows:
                summaries[row["summary_type"]] = {
                    "text": row["summary_text"],
                    "model_label": row["model_label"],
                    "generated_at": row["generated_at"].isoformat() if row["generated_at"] else None,
                }
                if row["summary_type"] == "frontier" and row["brave_followups"]:
                    followups_data = row["brave_followups"]
                    if isinstance(followups_data, str):
                        brave_followups = json.loads(followups_data)
                    else:
                        brave_followups = followups_data

        # Assemble the card page data
        # Derive OG variant URL from display URL by path convention
        display_url = card.image_url
        og_url = (
            display_url.replace("/display.png", "/og.png")
            if display_url and "/display.png" in display_url
            else None
        )

        now = datetime.now(timezone.utc)
        page_data = {
            "card_id": card_id,
            "collection_id": card.collection_id,
            "title": card.title,
            "summary": card.summary,
            "source_url": card.source_url,
            "source_type": card.source_type,
            "image_url": display_url,
            "image_url_og": og_url,
            "published_at": card.published_at.isoformat() if card.published_at else None,
            "source_date": card.source_date.isoformat() if card.source_date else None,
            "summaries": summaries,
            "brave_followups": brave_followups,
            "collection_name": collection.name if collection else "",
            "collection_slug": collection.slug if collection else "",
            "prev_card_id": card.prev_card_id,
            "next_card_id": card.next_card_id,
            "updated_at": now.isoformat(),
        }

        # Push to KV
        account_id, api_token, namespace_id = self._get_kv_credentials()

        kv_base_url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/storage/kv/namespaces/{namespace_id}/values"
        headers = {
            "Authorization": f"Bearer {api_token}",
            "Content-Type": "application/json",
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.put(
                    f"{kv_base_url}/card:{card_id}",
                    headers=headers,
                    data=json.dumps(page_data),
                ) as resp:
                    if resp.status != 200:
                        error_text = await resp.text()
                        raise CollectionError(
                            f"Cloudflare KV API error: {resp.status} - {error_text}",
                            guru_code="#COL.00000003.KVFAIL",
                        )

            logger.info(
                f"Synced card {card.title[:50]} to KV "
                f"({len(summaries)} summaries, {len(brave_followups)} followups)"
            )

            return {
                "success": True,
                "card_id": card_id,
                "summaries": list(summaries.keys()),
                "followups": len(brave_followups),
                "namespace_id": namespace_id,
            }

        except aiohttp.ClientError as e:
            raise CollectionError(
                f"Cloudflare KV network error: {e}",
                guru_code="#COL.00000003.KVFAIL",
            ) from e

    # =========================================================================
    # Per-Collection KV Sync
    # =========================================================================

    async def sync_collection_to_kv(
        self,
        collection_id: str,
    ) -> dict[str, Any]:
        """Sync a single collection's page data to Cloudflare KV.

        Assembles collection metadata, summaries, cards, and zettle aliases
        into a JSON blob and pushes to KV for the worker to render.

        Args:
            collection_id: Collection to sync

        Returns:
            Result dict with sync status

        Raises:
            CollectionError: If collection not found or KV push fails
        """
        import aiohttp
        import json

        # Fetch collection
        collection = await self.get_collection(collection_id)
        if not collection:
            raise CollectionError(
                f"Collection not found: {collection_id}",
                guru_code="#COL.00000001.NOTFOUND",
            )

        # Fetch summaries
        summaries: dict[str, Any] = {}
        async with self._pool.acquire() as conn:
            summary_rows = await conn.fetch(
                """
                SELECT summary_type, summary_text, model_label, generated_at
                FROM collections.collection_summaries
                WHERE collection_id = $1
                """,
                collection_id,
            )
            for row in summary_rows:
                summaries[row["summary_type"]] = {
                    "text": row["summary_text"],
                    "model_label": row["model_label"],
                    "generated_at": row["generated_at"].isoformat() if row["generated_at"] else None,
                }

        # Fetch published cards
        cards = await self.get_published_cards(collection_id=collection_id, limit=100)
        card_dicts = [card.to_public_dict() for card in cards]

        # Collect zettle-slug aliases from cards
        async with self._pool.acquire() as conn:
            alias_rows = await conn.fetch(
                """
                SELECT DISTINCT zettle_slug
                FROM collections.cards
                WHERE collection_id = $1 AND zettle_slug IS NOT NULL
                ORDER BY zettle_slug
                """,
                collection_id,
            )
        zettle_aliases = [row["zettle_slug"] for row in alias_rows]

        # Assemble the collection page data
        now = datetime.now(timezone.utc)
        page_data = {
            "collection_id": collection_id,
            "slug": collection.slug,
            "name": collection.name,
            "description": collection.description,
            "summaries": summaries,
            "zettle_aliases": zettle_aliases,
            "cards": card_dicts,
            "updated_at": now.isoformat(),
        }

        # Push to KV
        account_id, api_token, namespace_id = self._get_kv_credentials()

        kv_base_url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/storage/kv/namespaces/{namespace_id}/values"
        headers = {
            "Authorization": f"Bearer {api_token}",
            "Content-Type": "application/json",
        }

        try:
            async with aiohttp.ClientSession() as session:
                # 1. Put collection page data
                async with session.put(
                    f"{kv_base_url}/collection:{collection_id}",
                    headers=headers,
                    data=json.dumps(page_data),
                ) as resp:
                    if resp.status != 200:
                        error_text = await resp.text()
                        raise CollectionError(
                            f"Cloudflare KV API error: {resp.status} - {error_text}",
                            guru_code="#COL.00000003.KVFAIL",
                        )

                # 2. Put zettle-slug alias keys for slug-based lookup
                for alias in zettle_aliases:
                    alias_data = json.dumps({"collection_id": collection_id})
                    async with session.put(
                        f"{kv_base_url}/collection-alias:{alias}",
                        headers=headers,
                        data=alias_data,
                    ) as resp:
                        if resp.status != 200:
                            logger.warning(f"Failed to set alias key for {alias}: {resp.status}")

                # 3. Also set alias for collection slug itself
                slug_alias = json.dumps({"collection_id": collection_id})
                async with session.put(
                    f"{kv_base_url}/collection-alias:{collection.slug}",
                    headers=headers,
                    data=slug_alias,
                ) as resp:
                    if resp.status != 200:
                        logger.warning(f"Failed to set slug alias for {collection.slug}: {resp.status}")

            logger.info(
                f"Synced collection {collection.slug} to KV "
                f"({len(card_dicts)} cards, {len(zettle_aliases)} aliases)"
            )

            return {
                "success": True,
                "collection_id": collection_id,
                "slug": collection.slug,
                "cards_synced": len(card_dicts),
                "aliases_synced": len(zettle_aliases),
                "summaries": list(summaries.keys()),
                "namespace_id": namespace_id,
            }

        except aiohttp.ClientError as e:
            raise CollectionError(
                f"Cloudflare KV network error: {e}",
                guru_code="#COL.00000003.KVFAIL",
            ) from e

    async def sync_collections_index_to_kv(self) -> dict[str, Any]:
        """Sync the collections index to Cloudflare KV.

        Pushes a list of all active collections with card counts
        to the collections_index KV key for the index page.

        Returns:
            Result dict with sync status
        """
        import aiohttp
        import json

        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT
                    c.collection_id,
                    c.slug,
                    c.name,
                    c.description,
                    c.status,
                    c.featured,
                    COUNT(CASE WHEN card.status = 'published' THEN 1 END) as published_cards,
                    COUNT(card.card_id) as total_cards,
                    MAX(card.published_at) as last_published_at,
                    c.updated_at
                FROM collections.collections c
                LEFT JOIN collections.cards card ON c.collection_id = card.collection_id
                WHERE c.status = 'active'
                GROUP BY c.collection_id
                ORDER BY c.featured DESC, c.updated_at DESC
                """
            )

        index_entries = [
            {
                "collection_id": row["collection_id"],
                "slug": row["slug"],
                "name": row["name"],
                "description": row["description"] or "",
                "featured": row["featured"],
                "published_cards": row["published_cards"],
                "total_cards": row["total_cards"],
                "last_published_at": row["last_published_at"].isoformat() if row["last_published_at"] else None,
                "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
            }
            for row in rows
        ]

        # Push to KV
        account_id, api_token, namespace_id = self._get_kv_credentials()
        url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/storage/kv/namespaces/{namespace_id}/values/collections_index"
        headers = {
            "Authorization": f"Bearer {api_token}",
            "Content-Type": "application/json",
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.put(
                    url,
                    headers=headers,
                    data=json.dumps(index_entries),
                ) as resp:
                    if resp.status != 200:
                        error_text = await resp.text()
                        raise CollectionError(
                            f"Cloudflare KV API error: {resp.status} - {error_text}",
                            guru_code="#COL.00000003.KVFAIL",
                        )

            logger.info(f"Synced collections index to KV ({len(index_entries)} collections)")
            return {
                "success": True,
                "collections_synced": len(index_entries),
                "namespace_id": namespace_id,
            }

        except aiohttp.ClientError as e:
            raise CollectionError(
                f"Cloudflare KV network error: {e}",
                guru_code="#COL.00000003.KVFAIL",
            ) from e

    # =========================================================================
    # Private Helpers
    # =========================================================================

    def _row_to_collection(self, row: asyncpg.Record) -> Collection:
        """Convert database row to Collection object."""
        return Collection(
            collection_id=row["collection_id"],
            slug=row["slug"],
            name=row["name"],
            description=row.get("description") or "",
            status=row.get("status") or "draft",
            featured=row.get("featured") or False,
            grok_collection_id=row.get("grok_collection_id"),
            grok_last_sync_at=row.get("grok_last_sync_at"),
            series_enabled=row.get("series_enabled", True),
            kb_path=row.get("kb_path") or "",
            created_at=row.get("created_at"),
            updated_at=row.get("updated_at"),
        )

    def _row_to_card(self, row: asyncpg.Record) -> Card:
        """Convert database row to Card object."""
        return Card(
            card_id=row["card_id"],
            collection_id=row["collection_id"],
            title=row["title"],
            summary=row["summary"],
            source_url=row["source_url"],
            source_type=row["source_type"],
            image_url=row.get("image_url"),
            status=row.get("status") or "pending",
            published_at=row.get("published_at"),
            source_date=row.get("source_date"),
            sequence=row.get("sequence"),
            article_id=row.get("article_id"),
            prev_card_id=row.get("prev_card_id"),
            next_card_id=row.get("next_card_id"),
            kb_path=row.get("kb_path"),
            created_at=row.get("created_at"),
        )

    def _row_to_source(self, row: asyncpg.Record) -> Source:
        """Convert database row to Source object."""
        return Source(
            source_id=row["source_id"],
            card_id=row["card_id"],
            provenance_url=row["provenance_url"],
            provenance_traceable_id=row.get("provenance_traceable_id"),
            source_type=row.get("source_type") or "web",
            excerpt_text=row.get("excerpt_text"),
            excerpt_page=row.get("excerpt_page"),
            excerpt_section=row.get("excerpt_section"),
            excerpt_char_start=row.get("excerpt_char_start"),
            excerpt_char_end=row.get("excerpt_char_end"),
            ingested_via=row.get("ingested_via"),
            ingested_at=row.get("ingested_at"),
            kb_path=row.get("kb_path"),
        )

    def _row_to_article(self, row: asyncpg.Record) -> Article:
        """Convert database row to Article object."""
        return Article(
            article_id=row["article_id"],
            slug=row["slug"],
            title=row["title"],
            status=row.get("status") or "pending",
            kb_path=row.get("kb_path") or "",
            collection_id=row.get("collection_id"),
            current_version=row.get("current_version") or 0,
            zk_count=row.get("zk_count") or 0,
            sources_count=row.get("sources_count") or 0,
            arxiv_categories=row.get("arxiv_categories"),
            keywords=row.get("keywords"),
            created_at=row.get("created_at"),
            updated_at=row.get("updated_at"),
        )

    # ─────────────────────────────────────────────────────────────────────
    # Rendering (Blender Card Visualization via Workload Management)
    # ─────────────────────────────────────────────────────────────────────

    async def render_cards_stream(
        self,
        collection_slug: str = "",
        card_id: str = "",
        sample: int = 0,
        variants: list[str] | None = None,
        force: bool = False,
        upload: bool = True,
        orchestrator: Any = None,
    ) -> AsyncIterator[Any]:
        """Render card visualizations with GPU workload management.

        Flow:
        1. Query DB for cards to render
        2. Begin WORKLOAD_RENDERING (may evict idle vLLM endpoints)
        3. For each card: extract viz data -> render -> upload to R2
        4. Complete workload (restores evicted endpoints)
        5. Stream RenderCardEvent for each phase transition
        """
        import asyncio
        import time as time_mod
        from pathlib import Path
        from ..generated import (
            RenderCardEvent,
            RENDER_PHASE_QUEUED,
            RENDER_PHASE_ALLOCATING,
            RENDER_PHASE_RENDERING,
            RENDER_PHASE_UPLOADING,
            RENDER_PHASE_COMPLETE,
            RENDER_PHASE_FAILED,
            RENDER_PHASE_BATCH_COMPLETE,
        )

        batch_start = time_mod.time()

        # 1. Query cards to render
        cards_to_render = await self._query_cards_for_rendering(
            collection_slug=collection_slug,
            card_id=card_id,
            sample=sample,
            force=force,
        )

        if not cards_to_render:
            yield RenderCardEvent(
                phase=RENDER_PHASE_FAILED,
                message="No cards found matching criteria.",
                error="#VIZ.00000011.NOCARDS",
            )
            return

        total = len(cards_to_render)
        done = 0
        failed = 0

        # Determine which variants to render
        from gaius.viz.renderer import CARD_VARIANTS
        if variants:
            render_variants = {k: v for k, v in CARD_VARIANTS.items() if k in variants}
        else:
            render_variants = CARD_VARIANTS

        yield RenderCardEvent(
            phase=RENDER_PHASE_QUEUED,
            message=f"Rendering {total} card(s), variants: {list(render_variants.keys())}",
            cards_total=total,
        )

        # 2. Begin workload for GPU memory management
        workload_id = f"render-{uuid.uuid4().hex[:8]}"
        workload_started = False

        yield RenderCardEvent(
            phase=RENDER_PHASE_ALLOCATING,
            message="Requesting GPU resources for LuxCore rendering...",
            cards_total=total,
        )

        if not orchestrator:
            yield RenderCardEvent(
                phase=RENDER_PHASE_FAILED,
                message="Orchestrator not available — cannot manage GPU memory for rendering.\n"
                "  #VIZ.00000012.NOORCH\n"
                "  Try: just restart-clean",
            )
            return

        # Pick a single GPU to evict for rendering.
        # Rendering needs ~8GB (embeddings + Blender CUDA).
        # We evict one endpoint to free one full GPU (~24GB).
        target_gpu = await self._pick_render_gpu(orchestrator)

        try:
            from ..workloads import WorkloadRequest, WorkloadType
            from .scheduler_service import JobPriority

            workload_req = WorkloadRequest(
                workload_id=workload_id,
                workload_type=WorkloadType.RENDERING,
                required_capabilities=[],
                priority=JobPriority.HIGH,
                estimated_duration_s=total * 60,
                estimated_memory_mb=8000,
                preemptible=False,
                metadata={
                    "allow_baseline_eviction": True,
                    "target_gpus": [target_gpu],
                },
            )
            result = await orchestrator.begin_workload(workload_req)
            workload_started = True

            if not result.success:
                yield RenderCardEvent(
                    phase=RENDER_PHASE_FAILED,
                    message=f"Failed to allocate GPU resources: {result.error}",
                    error="#VIZ.00000013.ALLOCFAIL",
                )
                return

            if result.evicted_endpoints:
                yield RenderCardEvent(
                    phase=RENDER_PHASE_ALLOCATING,
                    message=f"Evicted {len(result.evicted_endpoints)} endpoint(s) for GPU memory: {', '.join(result.evicted_endpoints)}",
                    cards_total=total,
                )
            else:
                yield RenderCardEvent(
                    phase=RENDER_PHASE_ALLOCATING,
                    message="GPU memory already available (no eviction needed)",
                    cards_total=total,
                )
        except Exception as e:
            logger.error(f"Workload allocation failed: {e}")
            yield RenderCardEvent(
                phase=RENDER_PHASE_FAILED,
                message=f"GPU workload allocation failed: {e}\n"
                "  #VIZ.00000013.ALLOCFAIL",
                error=str(e),
            )
            return

        try:
            # 3. Render each card
            from gaius.viz.data import extract_card_viz_data
            from gaius.viz.renderer import render_card_variants_luxcore
            from gaius.viz.storage import upload_card_variants, update_card_image_url
            import tempfile

            render_semaphore = asyncio.Semaphore(2)

            for row in cards_to_render:
                cid = row["card_id"]
                card_start = time_mod.time()

                yield RenderCardEvent(
                    phase=RENDER_PHASE_RENDERING,
                    card_id=cid,
                    message=f"Rendering {cid} ({done + 1}/{total})",
                    progress=done / total,
                    cards_done=done,
                    cards_total=total,
                )

                try:
                    async with render_semaphore:
                        # Extract viz data (CPU embeddings to avoid CUDA
                        # context conflict with LuxCore on same GPU)
                        viz_data = await extract_card_viz_data(
                            self._pool, cid, device="cpu",
                        )

                        # Render all variants
                        output_dir = Path(tempfile.mkdtemp(prefix=f"gaius-viz-{cid}-"))
                        variant_paths = await render_card_variants_luxcore(
                            viz_data, output_dir, variants=render_variants,
                            gpu_id=target_gpu,
                        )

                    card_duration = int((time_mod.time() - card_start) * 1000)

                    # Upload to R2 if requested
                    if upload and variant_paths:
                        yield RenderCardEvent(
                            phase=RENDER_PHASE_UPLOADING,
                            card_id=cid,
                            message=f"Uploading {cid} to R2...",
                            cards_done=done,
                            cards_total=total,
                        )

                        try:
                            urls = await upload_card_variants(cid, variant_paths)
                            # Update DB with display variant URL
                            display_url = urls.get("display", "")
                            if display_url:
                                await update_card_image_url(self._pool, cid, display_url)

                            done += 1
                            yield RenderCardEvent(
                                phase=RENDER_PHASE_COMPLETE,
                                card_id=cid,
                                message=f"Rendered and uploaded {cid}",
                                image_url=display_url,
                                progress=done / total,
                                cards_done=done,
                                cards_total=total,
                                duration_ms=card_duration,
                            )
                        except Exception as e:
                            logger.error(f"R2 upload failed for {cid}: {e}")
                            done += 1
                            yield RenderCardEvent(
                                phase=RENDER_PHASE_COMPLETE,
                                card_id=cid,
                                message=f"Rendered {cid} (upload failed: {e})",
                                output_path=str(variant_paths.get("display", "")),
                                progress=done / total,
                                cards_done=done,
                                cards_total=total,
                                duration_ms=card_duration,
                            )
                    else:
                        done += 1
                        yield RenderCardEvent(
                            phase=RENDER_PHASE_COMPLETE,
                            card_id=cid,
                            message=f"Rendered {cid} (local only)",
                            output_path=str(variant_paths.get("display", "")),
                            progress=done / total,
                            cards_done=done,
                            cards_total=total,
                            duration_ms=card_duration,
                        )

                except Exception as e:
                    failed += 1
                    done += 1
                    logger.error(f"Render failed for card {cid}: {e}")
                    yield RenderCardEvent(
                        phase=RENDER_PHASE_FAILED,
                        card_id=cid,
                        message=f"Failed to render {cid}: {e}",
                        error=str(e),
                        progress=done / total,
                        cards_done=done,
                        cards_total=total,
                    )

        finally:
            # 4. Complete workload (restores evicted endpoints)
            if orchestrator and workload_started:
                try:
                    # Release embedding model from GPU before restoring vLLM.
                    # The ~3GB Nomic model on the render GPU causes NCCL init
                    # failures when vLLM tries tensor-parallel across that GPU.
                    from gaius.models.embeddings import clear_embeddings
                    clear_embeddings()

                    # Wait for GPU memory to be fully released (Blender CUDA
                    # context + embedding model) before vLLM starts.
                    logger.info("Waiting for GPU memory cleanup before restoring endpoints...")
                    await asyncio.sleep(10)
                    logger.info(f"Completing rendering workload {workload_id}, restoring endpoints...")
                    await orchestrator.complete_workload(workload_id)
                    logger.info(f"Completed rendering workload {workload_id}, endpoints restored")
                except Exception as e:
                    logger.error(f"Failed to complete workload {workload_id}: {e}")

        # 5. Batch complete
        batch_duration = int((time_mod.time() - batch_start) * 1000)
        succeeded = done - failed
        yield RenderCardEvent(
            phase=RENDER_PHASE_BATCH_COMPLETE,
            message=f"{done}/{total} cards rendered in {batch_duration / 1000:.1f}s ({succeeded} success, {failed} failed)",
            progress=1.0,
            cards_done=done,
            cards_total=total,
            duration_ms=batch_duration,
        )

    async def _query_cards_for_rendering(
        self,
        collection_slug: str = "",
        card_id: str = "",
        sample: int = 0,
        force: bool = False,
    ) -> list[Any]:
        """Query cards that need rendering.

        Args:
            collection_slug: Filter by collection (empty = all)
            card_id: Specific card ID (overrides collection)
            sample: Random sample N cards (0 = all matching)
            force: Include cards that already have image_url
        """
        async with self._pool.acquire() as conn:
            if card_id:
                # Specific card
                rows = await conn.fetch(
                    "SELECT card_id, collection_id, title FROM collections.cards WHERE card_id = $1",
                    card_id,
                )
                return list(rows)

            # Build query for cards needing renders
            conditions = ["c.status = 'published'"]
            params: list[Any] = []

            if not force:
                conditions.append("(c.image_url IS NULL OR c.image_url = '')")

            if collection_slug:
                params.append(collection_slug)
                conditions.append(f"col.slug = ${len(params)}")

            where = " AND ".join(conditions)

            if sample > 0:
                params.append(sample)
                query = f"""
                    SELECT c.card_id, c.collection_id, c.title
                    FROM collections.cards c
                    JOIN collections.collections col ON c.collection_id = col.collection_id
                    WHERE {where}
                    ORDER BY RANDOM()
                    LIMIT ${len(params)}
                """
            else:
                query = f"""
                    SELECT c.card_id, c.collection_id, c.title
                    FROM collections.cards c
                    JOIN collections.collections col ON c.collection_id = col.collection_id
                    WHERE {where}
                    ORDER BY c.created_at ASC
                """

            rows = await conn.fetch(query, *params)
            return list(rows)

    async def _pick_render_gpu(self, orchestrator: Any) -> int:
        """Pick a single GPU to evict for rendering.

        Strategy: choose the GPU with the most free memory (least valuable
        endpoint to evict). If GPU query fails, default to the last GPU
        (index 5 on a 6-GPU system) since baseline endpoints typically
        occupy GPUs 0-3 and overflow endpoints use 4-5.
        """
        try:
            from ..resources.gpu_monitor import get_gpu_memory_free

            gpu_free = await get_gpu_memory_free()
            if gpu_free:
                # Pick GPU with most free memory (cheapest to evict)
                best_gpu = max(gpu_free, key=gpu_free.get)  # type: ignore[arg-type]
                logger.info(
                    f"Selected GPU {best_gpu} for rendering "
                    f"({gpu_free[best_gpu]:.1f} GB free)"
                )
                return best_gpu
        except Exception as e:
            logger.warning(f"GPU query failed, using default: {e}")

        # Default: last GPU
        total_gpus = getattr(
            getattr(orchestrator, "resource_manager", None),
            "total_gpus", 6,
        )
        return total_gpus - 1


# Singleton instance
_service: CollectionService | None = None


def get_collection_service(pool: asyncpg.Pool | None = None) -> CollectionService:
    """Get or create the collection service singleton."""
    global _service
    if _service is None:
        if pool is None:
            raise CollectionError(
                "Database pool required for initialization",
                guru_code="#COL.00000002.DBFAIL",
            )
        _service = CollectionService(pool)
    return _service
