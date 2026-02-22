"""Common data classes and utilities for Article Curation Flow.

This module provides shared data structures used across the pipeline:
- ArticleCandidate: Represents an unpublished article found in KB
- ArticleStatus: State machine for article lifecycle
- AcquiredSource: External source acquired via fetchers
- DraftHistoryEntry: Metadata for drafts in hx/
- ArticleReference: BFO reference with character offsets
"""

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Optional

import yaml


class ArticleStatus(Enum):
    """Article lifecycle state machine.

    States:
        pending: Article created, awaiting research
        researching: KB research in progress
        drafting: Draft generation in progress
        review: Draft complete, awaiting review
        published: Article published externally
        abandoned: Article abandoned
    """

    PENDING = "pending"
    RESEARCHING = "researching"
    DRAFTING = "drafting"
    REVIEW = "review"
    PUBLISHED = "published"
    ABANDONED = "abandoned"


@dataclass
class ArticleCandidate:
    """An unpublished article found in KB.

    Represents an article directory at current/articles/{slug}/ that is
    ready for curation. The zk/ subdirectory contains zettelkasten notes
    that inform the research direction.

    Attributes:
        slug: Article identifier (directory name)
        title: Article title from frontmatter or H1
        status: Current lifecycle status
        kb_path: Path to article directory
        zk_count: Number of zettelkasten notes in zk/
        research_hints: Keywords/categories to guide research
        current_version: Current draft version number
        created_at: When article was created
        updated_at: Last modification time
        pending_cards: Number of pending cards in queue (for selection fairness)
        total_cards: Total cards ever created for this article
        last_curated_at: When article was last curated (for round-robin)
    """

    slug: str
    title: str
    status: ArticleStatus
    kb_path: str
    zk_count: int = 0
    research_hints: dict[str, Any] = field(default_factory=dict)
    current_version: int = 0
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    # Card backlog stats (populated from database for selection fairness)
    pending_cards: int = 0
    total_cards: int = 0
    last_curated_at: Optional[datetime] = None

    @classmethod
    def from_kb_path(cls, article_dir: Path) -> Optional["ArticleCandidate"]:
        """Create ArticleCandidate from KB article directory.

        Args:
            article_dir: Path to current/articles/{slug}/

        Returns:
            ArticleCandidate if valid, None if missing required files
        """
        if not article_dir.is_dir():
            return None

        slug = article_dir.name
        article_md = article_dir / "article.md"

        # Parse frontmatter if article.md exists
        title = slug.replace("-", " ").title()
        status = ArticleStatus.PENDING
        research_hints = {}
        current_version = 0
        created_at = None
        updated_at = None

        if article_md.exists():
            content = article_md.read_text()
            frontmatter = _parse_frontmatter(content)

            title = frontmatter.get("title", title)
            status_str = frontmatter.get("status", "pending")
            try:
                status = ArticleStatus(status_str)
            except ValueError:
                status = ArticleStatus.PENDING

            current_version = frontmatter.get("version", 0)

            # Extract research hints
            research_hints = {
                "arxiv_categories": frontmatter.get("arxiv_categories", []),
                "keywords": frontmatter.get("keywords", []),
                "news_queries": frontmatter.get("news_queries", []),
            }

            # Parse dates
            if created := frontmatter.get("created_at"):
                try:
                    created_at = datetime.fromisoformat(created.replace("Z", "+00:00"))
                except (ValueError, AttributeError):
                    pass
            if updated := frontmatter.get("updated_at"):
                try:
                    updated_at = datetime.fromisoformat(updated.replace("Z", "+00:00"))
                except (ValueError, AttributeError):
                    pass

        # Fallback title from H1 if not in frontmatter
        if title == slug.replace("-", " ").title() and article_md.exists():
            h1_title = _extract_h1_title(article_md.read_text())
            if h1_title:
                title = h1_title

        # Count zettelkasten notes
        zk_dir = article_dir / "zk"
        zk_count = len(list(zk_dir.glob("*.md"))) if zk_dir.exists() else 0

        return cls(
            slug=slug,
            title=title,
            status=status,
            kb_path=str(article_dir),
            zk_count=zk_count,
            research_hints=research_hints,
            current_version=current_version,
            created_at=created_at,
            updated_at=updated_at,
        )


@dataclass
class AcquiredSource:
    """External source acquired via fetchers.

    Represents content fetched from arxiv, biorxiv, brave, philpapers, etc.
    that will be added to the article's sources/ directory.

    Attributes:
        source_id: Unique identifier (e.g., src_arxiv_2401.12345)
        source_type: Fetcher type (arxiv, biorxiv, brave, philpapers, philevents)
        url: Public URL to original source
        title: Source title
        summary: Brief summary/abstract
        excerpt_text: Key excerpt for citation
        excerpt_char_start: Start offset in source document
        excerpt_char_end: End offset in source document
        traceable_id: TraceableId URI for provenance
        fetched_at: When source was acquired
        metadata: Additional source-specific metadata
    """

    source_id: str
    source_type: str
    url: str
    title: str
    summary: str = ""
    excerpt_text: str = ""
    excerpt_char_start: Optional[int] = None
    excerpt_char_end: Optional[int] = None
    traceable_id: Optional[str] = None
    fetched_at: Optional[datetime] = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def generate_id(cls, source_type: str, url: str) -> str:
        """Generate unique source ID from type and URL.

        Format: src_{type}_{hash[:12]}
        """
        url_hash = hashlib.sha256(url.encode()).hexdigest()[:12]
        return f"src_{source_type}_{url_hash}"

    @classmethod
    def from_fetcher_result(
        cls,
        source_type: str,
        url: str,
        title: str,
        summary: str = "",
        metadata: Optional[dict] = None,
    ) -> "AcquiredSource":
        """Create AcquiredSource from fetcher result."""
        # For web sources, preserve the full URL in traceable_id
        # so it can be reconstructed for card display
        if source_type == "web":
            traceable_id = f"web://{url}"
        else:
            # For known source types (arxiv, hf, doi), extract the identifier
            traceable_id = f"{source_type}://{url.split('/')[-1]}"

        return cls(
            source_id=cls.generate_id(source_type, url),
            source_type=source_type,
            url=url,
            title=title,
            summary=summary,
            traceable_id=traceable_id,
            fetched_at=datetime.now(),
            metadata=metadata or {},
        )

    def to_markdown(self) -> str:
        """Convert to markdown file content for KB storage."""
        frontmatter = {
            "type": "source",
            "source_id": self.source_id,
            "source_type": self.source_type,
            "url": self.url,
            "traceable_id": self.traceable_id,
            "fetched_at": self.fetched_at.isoformat() if self.fetched_at else None,
        }
        if self.excerpt_char_start is not None:
            frontmatter["excerpt_char_start"] = self.excerpt_char_start
        if self.excerpt_char_end is not None:
            frontmatter["excerpt_char_end"] = self.excerpt_char_end
        if self.metadata:
            frontmatter["metadata"] = self.metadata

        yaml_str = yaml.dump(frontmatter, default_flow_style=False, allow_unicode=True)

        content = f"""---
{yaml_str.strip()}
---

# {self.title}

{self.summary}
"""
        if self.excerpt_text:
            content += f"""
## Key Excerpt

> {self.excerpt_text}
"""
        return content


@dataclass
class DraftHistoryEntry:
    """Metadata for a draft in hx/.

    When a new draft is generated, the current article.md is archived
    to hx/ with timestamped filename and this metadata.

    Attributes:
        version: Draft version number
        timestamp: When draft was archived
        filename: Filename in hx/ (e.g., 20260201T143022_draft_v001.md)
        content_hash: SHA256 of draft content
        word_count: Number of words in draft
        source_count: Number of sources referenced
        generator_model: Model used to generate (e.g., grok-4-1-fast)
        generator_run_id: Metaflow run ID
        parent_version: Previous version this was based on
    """

    version: int
    timestamp: datetime
    filename: str
    content_hash: str
    word_count: int = 0
    source_count: int = 0
    generator_model: Optional[str] = None
    generator_run_id: Optional[str] = None
    parent_version: Optional[int] = None

    @classmethod
    def generate_filename(cls, version: int, timestamp: Optional[datetime] = None) -> str:
        """Generate draft history filename.

        Format: {ISO8601}_draft_v{version:03d}.md
        Example: 20260201T143022_draft_v001.md
        """
        ts = timestamp or datetime.now()
        iso_ts = ts.strftime("%Y%m%dT%H%M%S")
        return f"{iso_ts}_draft_v{version:03d}.md"

    @classmethod
    def from_content(
        cls,
        content: str,
        version: int,
        generator_model: Optional[str] = None,
        generator_run_id: Optional[str] = None,
        parent_version: Optional[int] = None,
    ) -> "DraftHistoryEntry":
        """Create DraftHistoryEntry from draft content."""
        timestamp = datetime.now()
        content_hash = hashlib.sha256(content.encode()).hexdigest()
        word_count = len(content.split())

        # Count source references (<!-- ref:ref_NNN --> markers)
        source_count = len(re.findall(r"<!-- ref:ref_\d+ -->", content))

        return cls(
            version=version,
            timestamp=timestamp,
            filename=cls.generate_filename(version, timestamp),
            content_hash=content_hash,
            word_count=word_count,
            source_count=source_count,
            generator_model=generator_model,
            generator_run_id=generator_run_id,
            parent_version=parent_version,
        )


class CardStatus(str, Enum):
    """Publication status of a card for a reference.

    Tracks whether a card has been created and published for a
    specific ref_start/ref_end pair in the article.
    """

    UNKNOWN = "unknown"  # Status not yet determined
    PENDING = "pending"  # Card created but not published
    PUBLISHED = "published"  # Card published to landing page
    SKIPPED = "skipped"  # Intentionally not publishing
    ARCHIVED = "archived"  # Previously published, now archived


@dataclass
class ArticleReference:
    """A reference in the BFO Base file with character offsets.

    Used to link specific passages in the article to source materials
    with precise character-level citations.

    Attributes:
        ref_id: Reference identifier (e.g., ref_001)
        source_id: Source document identifier
        traceable_id: TraceableId URI for provenance
        ref_start: Character offset start in SOURCE document (-1 if no specific offset)
        ref_end: Character offset end in SOURCE document (-1 if no specific offset)
        excerpt: Preview text (for .base file display only)
        title: Source title (from arXiv, etc.) - used for card display
        brief_summary: LLM-generated summary of the cited passage (or whole source if no offsets)
        extracted_path: Relative path to OCR-extracted markdown (docling, etc.)
        iao_type: IAO ontology type (default: IAO:0000300 textual entity)
        card_status: Publication status for this reference's card
    """

    ref_id: str
    source_id: str
    traceable_id: str
    ref_start: int
    ref_end: int
    excerpt: str
    title: str = ""
    brief_summary: str = ""
    extracted_path: str = ""
    iao_type: str = "IAO:0000300"
    card_status: CardStatus = CardStatus.UNKNOWN

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for YAML frontmatter."""
        result = {
            "ref_id": self.ref_id,
            "source_id": self.source_id,
            "traceable_id": self.traceable_id,
            "ref_start": self.ref_start,
            "ref_end": self.ref_end,
            "excerpt": self.excerpt,
            "iao_type": self.iao_type,
            "card_status": self.card_status.value,
        }
        if self.title:
            result["title"] = self.title
        if self.brief_summary:
            result["brief_summary"] = self.brief_summary
        if self.extracted_path:
            result["extracted_path"] = self.extracted_path
        return result


def _parse_frontmatter(content: str) -> dict[str, Any]:
    """Parse YAML frontmatter from markdown content.

    Args:
        content: Markdown content with optional YAML frontmatter

    Returns:
        Parsed frontmatter dict (empty if none found)
    """
    if not content.startswith("---"):
        return {}

    # Find closing ---
    end_match = re.search(r"\n---\s*\n", content[3:])
    if not end_match:
        return {}

    yaml_content = content[3 : end_match.start() + 3]
    try:
        return yaml.safe_load(yaml_content) or {}
    except yaml.YAMLError:
        return {}


def _extract_h1_title(content: str) -> Optional[str]:
    """Extract H1 title from markdown content.

    Args:
        content: Markdown content

    Returns:
        H1 title text or None if not found
    """
    # Skip frontmatter
    if content.startswith("---"):
        end_match = re.search(r"\n---\s*\n", content[3:])
        if end_match:
            content = content[end_match.end() + 3 :]

    # Find first H1
    match = re.search(r"^#\s+(.+)$", content, re.MULTILINE)
    return match.group(1).strip() if match else None


def scan_articles(kb_root: str | Path) -> list[ArticleCandidate]:
    """Scan KB for unpublished articles.

    Scans current/articles/*/ for article directories with pending or
    researching status that have zettelkasten notes in zk/.

    Args:
        kb_root: KB root directory (e.g., build/dev)

    Returns:
        List of ArticleCandidate objects sorted by created_at
    """
    kb_root = Path(kb_root)
    articles_dir = kb_root / "current" / "articles"

    if not articles_dir.exists():
        return []

    candidates = []
    for article_dir in articles_dir.iterdir():
        if not article_dir.is_dir():
            continue

        candidate = ArticleCandidate.from_kb_path(article_dir)
        if candidate and candidate.status in (
            ArticleStatus.PENDING,
            ArticleStatus.RESEARCHING,
            ArticleStatus.DRAFTING,  # Include for iterative refinement
        ):
            # Only include articles with at least one zk/ note
            if candidate.zk_count > 0:
                candidates.append(candidate)

    # Sort by created_at (oldest first)
    # Use naive datetime for comparison to avoid timezone issues
    def sort_key(c: ArticleCandidate) -> datetime:
        if c.created_at is None:
            return datetime.min
        # Convert to naive datetime for consistent comparison
        if c.created_at.tzinfo is not None:
            return c.created_at.replace(tzinfo=None)
        return c.created_at

    candidates.sort(key=sort_key)
    return candidates


def get_kb_root() -> Path:
    """Get KB root directory from environment or default."""
    return Path(os.environ.get("GAIUS_KB_ROOT", "build/dev"))


async def fetch_article_card_stats(slugs: list[str]) -> dict[str, dict[str, Any]]:
    """Fetch card statistics for articles from database.

    Queries the collections schema for pending/total card counts and
    last curation time per article. Used to inform fair article selection.

    Args:
        slugs: List of article slugs to fetch stats for

    Returns:
        Dict mapping slug -> {pending_cards, total_cards, last_curated_at}
    """
    import asyncpg

    from gaius.core.config import get_database_url
    db_url = get_database_url()

    stats: dict[str, dict[str, Any]] = {slug: {} for slug in slugs}

    try:
        conn = await asyncpg.connect(db_url)
        try:
            rows = await conn.fetch(
                """
                SELECT
                    a.slug,
                    COUNT(c.card_id) FILTER (WHERE c.status = 'pending') as pending_cards,
                    COUNT(c.card_id) as total_cards,
                    MAX(c.created_at) as last_card_created
                FROM collections.articles a
                LEFT JOIN collections.cards c ON c.article_id = a.article_id
                WHERE a.slug = ANY($1)
                GROUP BY a.slug
                """,
                slugs,
            )
            for row in rows:
                stats[row["slug"]] = {
                    "pending_cards": row["pending_cards"] or 0,
                    "total_cards": row["total_cards"] or 0,
                    "last_curated_at": row["last_card_created"],
                }
        finally:
            await conn.close()
    except Exception as e:
        # Non-fatal: return empty stats, selection proceeds without balance info
        import logging
        logging.getLogger(__name__).warning(f"Failed to fetch card stats: {e}")

    return stats


def find_extracted_path(kb_root: Path, traceable_id: str) -> str:
    """Find extracted markdown path for a traceable_id.

    Searches scratch/{date}/ for docling-extracted markdown matching the
    traceable_id (e.g., arxiv://2401.12345 -> file with arxiv_id: 2401.12345).

    Args:
        kb_root: KB root directory (e.g., build/dev)
        traceable_id: TraceableId URI like arxiv://2401.12345v1

    Returns:
        Relative path to extracted markdown, or empty string if not found
    """
    if not traceable_id:
        return ""

    # Parse scheme and ID
    match = re.match(r"^(\w+)://(.+)$", traceable_id)
    if not match:
        return ""

    scheme, raw_id = match.groups()

    if scheme != "arxiv":
        # Only arXiv docling extraction is currently supported
        return ""

    # Strip version suffix: 2401.12345v1 -> 2401.12345
    arxiv_id = re.sub(r"v\d+$", "", raw_id)

    scratch_dir = kb_root / "scratch"
    if not scratch_dir.exists():
        return ""

    # Search recent dates first (reverse chronological)
    for date_dir in sorted(scratch_dir.iterdir(), reverse=True):
        if not date_dir.is_dir():
            continue

        # Look for arxiv markdown files
        for md_file in date_dir.glob("*_arxiv_*.md"):
            # Check frontmatter for matching arxiv_id
            try:
                content = md_file.read_text()
                if not content.startswith("---"):
                    continue

                # Quick check for arxiv_id in frontmatter
                if f'arxiv_id: "{arxiv_id}"' in content or f"arxiv_id: {arxiv_id}" in content:
                    # Return relative path from kb_root
                    return str(md_file.relative_to(kb_root))
            except Exception:
                continue

    return ""
