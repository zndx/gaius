"""Common data classes and utilities for CardUpkeepFlow.

This module provides shared data structures and helper functions:
- ArticleProcessResult: Result of processing a single article
- scan_base_files: Find .base files with eligible references
- parse_base_file: Parse YAML frontmatter from .base file
- update_base_file: Update card_status in .base file
- traceable_id_to_url: Convert traceable IDs to public URLs
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from gaius.flows.article_curation.common import ArticleReference, CardStatus


@dataclass
class ArticleProcessResult:
    """Result of processing a single article in the foreach branch.

    Captures success/failure and metrics for aggregation in join step.
    """

    article_path: str
    slug: str
    success: bool
    cards_created: int = 0
    cards_already_pending: int = 0
    error: str | None = None
    duration_ms: float = 0.0
    card_ids: list[str] = field(default_factory=list)
    ref_ids_processed: list[str] = field(default_factory=list)


def scan_base_files(
    kb_root: Path,
    article_slug: str | None = None,
    max_articles: int = 3,
) -> list[tuple[Path, list[ArticleReference]]]:
    """Find .base files with references where card_status in [unknown, pending].

    Args:
        kb_root: KB root directory (e.g., build/dev)
        article_slug: Specific article to process (or None for all)
        max_articles: Maximum number of articles to return

    Returns:
        List of (base_path, eligible_references) tuples
    """
    articles_dir = kb_root / "current" / "articles"
    if not articles_dir.exists():
        return []

    results: list[tuple[Path, list[ArticleReference]]] = []

    # Filter to specific article if requested
    if article_slug:
        article_dirs = [articles_dir / article_slug]
    else:
        article_dirs = [d for d in articles_dir.iterdir() if d.is_dir()]

    for article_dir in article_dirs:
        if not article_dir.exists():
            continue

        # Find most recent .base file
        base_files = list(article_dir.glob("*.base"))
        if not base_files:
            continue

        # Sort by modification time, get most recent
        base_files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        base_path = base_files[0]

        # Parse and filter references
        try:
            _, references = parse_base_file(base_path)
            eligible = [
                ref for ref in references
                if ref.card_status in (CardStatus.UNKNOWN, CardStatus.PENDING)
            ]

            if eligible:
                results.append((base_path, eligible))
        except Exception:
            # Skip unparseable files
            continue

        if len(results) >= max_articles:
            break

    return results


def parse_base_file(base_path: Path) -> tuple[dict[str, Any], list[ArticleReference]]:
    """Parse YAML frontmatter from .base file.

    Args:
        base_path: Path to .base file

    Returns:
        Tuple of (full_data_dict, list_of_references)

    Raises:
        ValueError: If file format is invalid
    """
    content = base_path.read_text()

    # Parse YAML frontmatter (between --- markers)
    if not content.startswith("---"):
        raise ValueError(f"Invalid .base file format: {base_path}")

    # Split on --- and take the YAML section
    parts = content.split("---", 2)
    if len(parts) < 2:
        raise ValueError(f"Invalid .base file format: {base_path}")

    yaml_content = parts[1]
    data = yaml.safe_load(yaml_content)

    if not data:
        raise ValueError(f"Empty YAML in .base file: {base_path}")

    # Parse references
    references: list[ArticleReference] = []
    for ref_data in data.get("references", []):
        ref = ArticleReference(
            ref_id=ref_data["ref_id"],
            source_id=ref_data["source_id"],
            traceable_id=ref_data.get("traceable_id", ""),
            ref_start=ref_data.get("ref_start", 0),
            ref_end=ref_data.get("ref_end", 0),
            excerpt=ref_data.get("excerpt", ""),
            title=ref_data.get("title", ""),
            brief_summary=ref_data.get("brief_summary", ""),
            extracted_path=ref_data.get("extracted_path", ""),
            iao_type=ref_data.get("iao_type", "IAO:0000300"),
            card_status=CardStatus(ref_data.get("card_status", "unknown")),
        )
        references.append(ref)

    return data, references


def update_base_file(
    base_path: Path,
    ref_updates: dict[str, CardStatus],
) -> int:
    """Update card_status for specific ref_ids in .base file.

    Args:
        base_path: Path to .base file
        ref_updates: Dict mapping ref_id -> new CardStatus

    Returns:
        Number of references updated

    Raises:
        ValueError: If file format is invalid
    """
    content = base_path.read_text()

    # Parse YAML frontmatter
    if not content.startswith("---"):
        raise ValueError(f"Invalid .base file format: {base_path}")

    parts = content.split("---", 2)
    if len(parts) < 2:
        raise ValueError(f"Invalid .base file format: {base_path}")

    yaml_content = parts[1]
    data = yaml.safe_load(yaml_content)

    if not data:
        raise ValueError(f"Empty YAML in .base file: {base_path}")

    # Update references
    updated_count = 0
    for ref_data in data.get("references", []):
        ref_id = ref_data.get("ref_id")
        if ref_id in ref_updates:
            ref_data["card_status"] = ref_updates[ref_id].value
            updated_count += 1

    # Write back
    yaml_content = yaml.dump(data, default_flow_style=False, allow_unicode=True)
    base_path.write_text(f"---\n{yaml_content}---\n")

    return updated_count


def traceable_id_to_url(traceable_id: str) -> str:
    """Convert traceable IDs to public URLs.

    Args:
        traceable_id: URI like arxiv://2601.22156v1

    Returns:
        Public URL like https://arxiv.org/abs/2601.22156

    Examples:
        arxiv://2601.22156v1 -> https://arxiv.org/abs/2601.22156
        hf://facebook/opt-350m -> https://huggingface.co/facebook/opt-350m
    """
    if not traceable_id:
        return ""

    # Parse scheme and path
    match = re.match(r"^(\w+)://(.+)$", traceable_id)
    if not match:
        return traceable_id  # Return as-is if not a URI

    scheme, path = match.groups()

    if scheme == "arxiv":
        # arxiv://2601.22156v1 -> https://arxiv.org/abs/2601.22156
        # Strip version suffix for cleaner URL
        arxiv_id = re.sub(r"v\d+$", "", path)
        return f"https://arxiv.org/abs/{arxiv_id}"

    elif scheme == "hf":
        # hf://facebook/opt-350m -> https://huggingface.co/facebook/opt-350m
        return f"https://huggingface.co/{path}"

    elif scheme == "doi":
        # doi://10.1234/example -> https://doi.org/10.1234/example
        return f"https://doi.org/{path}"

    elif scheme == "web":
        # web://https://example.com/page -> https://example.com/page
        # The path contains the full original URL
        return path

    elif scheme in ("http", "https"):
        # Already a URL
        return traceable_id

    else:
        # Unknown scheme, return as-is
        return traceable_id


def extract_source_type(traceable_id: str) -> str:
    """Extract source type from traceable ID scheme.

    Args:
        traceable_id: URI like arxiv://2601.22156v1

    Returns:
        Source type string for Card.source_type
    """
    if not traceable_id:
        return "web"

    match = re.match(r"^(\w+)://", traceable_id)
    if not match:
        return "web"

    scheme = match.group(1).lower()

    # Map schemes to Card source_type values
    scheme_map = {
        "arxiv": "arxiv",
        "hf": "huggingface",
        "doi": "research",
        "http": "web",
        "https": "web",
    }

    return scheme_map.get(scheme, "web")


def _strip_frontmatter(content: str) -> str:
    """Strip YAML frontmatter from markdown content.

    Args:
        content: Markdown content with optional YAML frontmatter

    Returns:
        Content body without frontmatter
    """
    if not content.startswith("---"):
        return content

    # Find closing ---
    end_match = re.search(r"\n---\s*\n", content[3:])
    if not end_match:
        return content

    return content[end_match.end() + 3 :].strip()


def load_extracted_text(kb_root: Path, extracted_path: str) -> str | None:
    """Load full OCR-extracted markdown text.

    Args:
        kb_root: KB root (e.g., build/dev)
        extracted_path: Relative path to extracted markdown (docling, etc.)

    Returns:
        Full extracted text (body only, no frontmatter), or None if not found
    """
    if not extracted_path:
        return None

    full_path = kb_root / extracted_path
    if not full_path.exists():
        return None

    content = full_path.read_text()
    return _strip_frontmatter(content)


def extract_card_content(
    extracted_text: str,
    ref_start: int,
    ref_end: int,
) -> str:
    """Extract card content slice from extracted text using offsets.

    Cards use the specific passage delimited by ref_start:ref_end,
    not the full extracted document.

    Args:
        extracted_text: Full extracted text (from load_extracted_text)
        ref_start: Character offset start
        ref_end: Character offset end

    Returns:
        Extracted text slice [ref_start:ref_end]

    Raises:
        ValueError: If offsets are invalid (0,0 placeholders or out of bounds)
    """
    if ref_start == 0 and ref_end == 0:
        raise ValueError(
            "Invalid offsets (0,0) - ArticleCurationFlow must set real offsets. "
            "#CUF.00000009.BADOFFSET"
        )

    if ref_end > len(extracted_text):
        raise ValueError(
            f"ref_end ({ref_end}) exceeds text length ({len(extracted_text)}). "
            "#CUF.00000010.OFFSETOOB"
        )

    return extracted_text[ref_start:ref_end]


def reset_card_statuses(
    base_path: Path,
    target_status: CardStatus = CardStatus.UNKNOWN,
) -> int:
    """Reset all card_status values in a .base file.

    Useful for reprocessing references when card content was incorrect.

    Args:
        base_path: Path to .base file
        target_status: Status to set (default: unknown)

    Returns:
        Number of references reset

    Raises:
        ValueError: If file format is invalid
    """
    content = base_path.read_text()

    # Parse YAML frontmatter
    if not content.startswith("---"):
        raise ValueError(f"Invalid .base file format: {base_path}")

    parts = content.split("---", 2)
    if len(parts) < 2:
        raise ValueError(f"Invalid .base file format: {base_path}")

    yaml_content = parts[1]
    data = yaml.safe_load(yaml_content)

    if not data:
        raise ValueError(f"Empty YAML in .base file: {base_path}")

    # Reset all references
    reset_count = 0
    for ref_data in data.get("references", []):
        old_status = ref_data.get("card_status", "unknown")
        if old_status != target_status.value:
            ref_data["card_status"] = target_status.value
            reset_count += 1

    # Write back
    yaml_content = yaml.dump(data, default_flow_style=False, allow_unicode=True)
    base_path.write_text(f"---\n{yaml_content}---\n")

    return reset_count
