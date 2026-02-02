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
"""

from __future__ import annotations

import logging
import os
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, AsyncIterator

import asyncpg

logger = logging.getLogger(__name__)


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
            article_id: Article ID for FK relationship (optional during transition)

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
                 image_url, sequence, article_id, created_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                """,
                card_id, collection_id, title, summary, source_url, source_type,
                image_url, sequence, article_id, now,
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
            created_at=now,
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
        """Publish pending cards from a collection.

        Marks cards as published and returns them for KV sync.

        Args:
            count: Number of cards to publish (default: 3)
            collection_id: Collection to publish from (default: featured)

        Returns:
            List of newly published cards
        """
        count = min(count, self._config.max_cards_per_publish)

        async with self._pool.acquire() as conn:
            if collection_id:
                # Publish from specific collection
                rows = await conn.fetch(
                    """
                    WITH pending AS (
                        SELECT card_id FROM collections.cards
                        WHERE collection_id = $1 AND status = 'pending'
                        ORDER BY sequence ASC, created_at ASC
                        LIMIT $2
                        FOR UPDATE
                    )
                    UPDATE collections.cards
                    SET status = 'published', published_at = NOW(), updated_at = NOW()
                    WHERE card_id IN (SELECT card_id FROM pending)
                    RETURNING *
                    """,
                    collection_id, count,
                )
            else:
                # Publish from featured collection
                rows = await conn.fetch(
                    """
                    WITH featured_col AS (
                        SELECT collection_id FROM collections.collections
                        WHERE featured = TRUE
                    ),
                    pending AS (
                        SELECT c.card_id FROM collections.cards c
                        JOIN featured_col fc ON c.collection_id = fc.collection_id
                        WHERE c.status = 'pending'
                        ORDER BY c.sequence ASC, c.created_at ASC
                        LIMIT $1
                        FOR UPDATE OF c
                    )
                    UPDATE collections.cards
                    SET status = 'published', published_at = NOW(), updated_at = NOW()
                    WHERE card_id IN (SELECT card_id FROM pending)
                    RETURNING *
                    """,
                    count,
                )

            published = [self._row_to_card(row) for row in rows]

            logger.info(f"Published {len(published)} cards")
            return published

    async def get_cards_for_kv(self, limit: int = 50) -> list[dict[str, Any]]:
        """Get published cards in format suitable for Cloudflare KV.

        Returns cards as public dicts ready for JSON serialization.
        """
        cards = await self.get_published_cards(limit=limit)
        return [card.to_public_dict() for card in cards]

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
        # Get KV config from environment (prefer env vars over config)
        # Use CLOUDFLARE_COLLECTIONS_KV_NAMESPACE_ID for collections (GAIUS_COLLECTIONS namespace)
        # This is distinct from CLOUDFLARE_KV_NAMESPACE_ID which is used for sessions (GAIUS_SESSIONS)
        account_id = os.environ.get("CLOUDFLARE_ACCOUNT_ID", self._config.cf_account_id)
        api_token = os.environ.get("CLOUDFLARE_API_TOKEN", self._config.cf_api_token)
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

        # Sync to KV
        sync_result = {"success": False, "cards_synced": 0}
        try:
            sync_result = await self.sync_to_kv()
        except CollectionError as e:
            logger.error(f"KV sync failed: {e}")

        return {
            "published": [card.to_public_dict() for card in published],
            "published_count": len(published),
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
            slug: URL-friendly identifier
            title: Display title (defaults to title-cased slug)

        Returns:
            Dict with slug, title, kb_path, article_id, collection_id

        Raises:
            CollectionError: If article already exists or creation fails
        """
        from pathlib import Path
        import yaml
        from datetime import datetime

        if not title:
            title = slug.replace("-", " ").title()

        kb_root = Path(self._config.kb_root)
        article_dir = kb_root / "current" / "articles" / slug
        kb_path = f"current/articles/{slug}"

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
                slug=slug,
                title=title,
                kb_path=kb_path,
            )

            logger.info(f"Created article '{slug}' at {article_dir}")

            return {
                "slug": slug,
                "title": title,
                "kb_path": str(article_dir),
                "article_id": article.article_id,
                "collection_id": collection.collection_id,
                "message": f"Created article '{title}' at {article_dir}. Add research notes to zk/ then run /article curate {slug}",
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
        db_url = os.environ.get(
            "GAIUS_DATABASE_URL",
            "postgres://gaius:gaius@localhost:5438/zndx_gaius"
        )

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
                    # Run Metaflow flow module directly (not metaflow.cli)
                    cmd = [
                        "uv", "run", "python", "-m", "gaius.flows.article_curation.flow",
                        "run",
                    ]
                    if slug:
                        cmd.extend(["--article", slug])

                    logger.info(f"Starting article curation: {' '.join(cmd)}")

                    # Run Metaflow as subprocess
                    # Uses inherited Metaflow configuration from environment
                    process = await asyncio.create_subprocess_exec(
                        *cmd,
                        cwd=os.environ.get("GAIUS_PROJECT_ROOT", os.getcwd()),
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                        env={
                            **os.environ,
                            "GAIUS_KB_ROOT": self._config.kb_root,
                        },
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
                    # Signal completion
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
