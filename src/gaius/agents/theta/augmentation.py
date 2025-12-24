"""KB augmentation module for ThetaAgent consolidation.

Materializes discovered subsumptions as:
- Wikilinks: [[concept]] direct links
- action:search: Soft semantic links [action:search "query"]
- Frontmatter relations: YAML relates_to fields

All augmentations are wrapped in structured markers for holdout testing.
"""

import re
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

import logging

logger = logging.getLogger(__name__)


# Augmentation block markers
BEGIN_MARKER = "<!-- BEGIN THETA_AUGMENTATION"
END_MARKER = "<!-- END THETA_AUGMENTATION -->"

# Regex to match augmentation block
AUGMENTATION_BLOCK_RE = re.compile(
    r"<!-- BEGIN THETA_AUGMENTATION.*?-->.*?<!-- END THETA_AUGMENTATION -->",
    re.DOTALL,
)


@dataclass
class AugmentationResult:
    """Result of a KB augmentation operation.

    Attributes:
        document_path: Path to augmented document
        augmentation_type: Type of augmentation (wikilink, action_search, frontmatter)
        content_added: The augmentation content that was added
        slice_id: Temporal slice identifier
        cycle_id: Consolidation cycle identifier
        wikilinks_added: Number of wikilinks added
        action_links_added: Number of action links added
    """

    document_path: Path
    augmentation_type: str
    content_added: str
    slice_id: str
    cycle_id: str
    wikilinks_added: int = 0
    action_links_added: int = 0


def create_augmentation_block(
    wikilinks: list[str],
    action_links: list[str],
    slice_id: str,
    cycle_id: str | None = None,
    timestamp: datetime | None = None,
) -> str:
    """Create a structured augmentation block.

    Args:
        wikilinks: List of concepts to link as [[concept]]
        action_links: List of search queries for [action:search "query"]
        slice_id: Temporal slice identifier
        cycle_id: Optional consolidation cycle identifier
        timestamp: Optional timestamp (default: now)

    Returns:
        Formatted augmentation block string
    """
    if cycle_id is None:
        cycle_id = str(uuid.uuid4())[:8]
    if timestamp is None:
        timestamp = datetime.now()

    # Build header
    header = f"{BEGIN_MARKER} slice={slice_id} cycle_id={cycle_id} timestamp={timestamp.isoformat()} -->"

    # Build content
    lines = ["", "## Related Concepts (Consolidation)", ""]

    if wikilinks:
        for concept in wikilinks:
            lines.append(f"- [[{concept}]]")

    if action_links:
        if wikilinks:
            lines.append("")  # Separator
        for query in action_links:
            lines.append(f"- [action:search \"{query}\"]")

    lines.append("")
    lines.append(END_MARKER)

    return header + "\n".join(lines)


def inject_wikilinks(
    content: str,
    concepts: list[str],
    slice_id: str,
    cycle_id: str | None = None,
) -> tuple[str, int]:
    """Inject wikilinks into document content.

    Adds a structured augmentation block at the end of the document.

    Args:
        content: Original document content
        concepts: List of concepts to link
        slice_id: Temporal slice identifier
        cycle_id: Optional consolidation cycle identifier

    Returns:
        Tuple of (augmented content, number of links added)
    """
    if not concepts:
        return content, 0

    # Remove any existing augmentation block first
    content = strip_augmentation(content)

    # Create augmentation block
    block = create_augmentation_block(
        wikilinks=concepts,
        action_links=[],
        slice_id=slice_id,
        cycle_id=cycle_id,
    )

    # Append to content
    augmented = content.rstrip() + "\n\n" + block

    return augmented, len(concepts)


def inject_action_links(
    content: str,
    queries: list[str],
    slice_id: str,
    cycle_id: str | None = None,
) -> tuple[str, int]:
    """Inject action:search links into document content.

    Args:
        content: Original document content
        queries: List of search queries
        slice_id: Temporal slice identifier
        cycle_id: Optional consolidation cycle identifier

    Returns:
        Tuple of (augmented content, number of links added)
    """
    if not queries:
        return content, 0

    # Remove any existing augmentation block first
    content = strip_augmentation(content)

    # Create augmentation block
    block = create_augmentation_block(
        wikilinks=[],
        action_links=queries,
        slice_id=slice_id,
        cycle_id=cycle_id,
    )

    # Append to content
    augmented = content.rstrip() + "\n\n" + block

    return augmented, len(queries)


def inject_mixed(
    content: str,
    wikilinks: list[str],
    action_links: list[str],
    slice_id: str,
    cycle_id: str | None = None,
) -> tuple[str, int, int]:
    """Inject both wikilinks and action links.

    Args:
        content: Original document content
        wikilinks: List of concepts to link
        action_links: List of search queries
        slice_id: Temporal slice identifier
        cycle_id: Optional consolidation cycle identifier

    Returns:
        Tuple of (augmented content, wikilinks added, action links added)
    """
    if not wikilinks and not action_links:
        return content, 0, 0

    # Remove any existing augmentation block first
    content = strip_augmentation(content)

    # Create augmentation block
    block = create_augmentation_block(
        wikilinks=wikilinks,
        action_links=action_links,
        slice_id=slice_id,
        cycle_id=cycle_id,
    )

    # Append to content
    augmented = content.rstrip() + "\n\n" + block

    return augmented, len(wikilinks), len(action_links)


def strip_augmentation(content: str) -> str:
    """Remove augmentation block from content.

    Used for holdout testing - retrieves original content without augmentations.

    Args:
        content: Document content potentially containing augmentation

    Returns:
        Content with augmentation block removed
    """
    return AUGMENTATION_BLOCK_RE.sub("", content).rstrip()


def extract_augmentation(content: str) -> Optional[str]:
    """Extract augmentation block from content.

    Args:
        content: Document content

    Returns:
        Augmentation block if found, None otherwise
    """
    match = AUGMENTATION_BLOCK_RE.search(content)
    return match.group(0) if match else None


def parse_augmentation_metadata(content: str) -> Optional[dict]:
    """Parse metadata from augmentation block header.

    Args:
        content: Document content

    Returns:
        Dict with slice_id, cycle_id, timestamp if found
    """
    match = re.search(
        r"<!-- BEGIN THETA_AUGMENTATION\s+"
        r"slice=(\S+)\s+"
        r"cycle_id=(\S+)\s+"
        r"timestamp=(\S+)\s*-->",
        content,
    )
    if not match:
        return None

    return {
        "slice_id": match.group(1),
        "cycle_id": match.group(2),
        "timestamp": match.group(3),
    }


def has_augmentation(content: str) -> bool:
    """Check if content has an augmentation block.

    Args:
        content: Document content

    Returns:
        True if augmentation block exists
    """
    return BEGIN_MARKER in content and END_MARKER in content


async def augment_document(
    document_path: Path,
    wikilinks: list[str],
    action_links: list[str],
    slice_id: str,
    cycle_id: str | None = None,
    dry_run: bool = False,
) -> AugmentationResult:
    """Augment a KB document with consolidation links.

    Args:
        document_path: Path to markdown document
        wikilinks: Concepts to add as [[concept]] links
        action_links: Queries to add as [action:search "query"]
        slice_id: Temporal slice identifier
        cycle_id: Optional consolidation cycle identifier
        dry_run: If True, don't write changes

    Returns:
        AugmentationResult with details of changes made
    """
    if cycle_id is None:
        cycle_id = str(uuid.uuid4())[:8]

    # Read current content
    content = document_path.read_text()

    # Apply augmentation
    augmented, wiki_count, action_count = inject_mixed(
        content=content,
        wikilinks=wikilinks,
        action_links=action_links,
        slice_id=slice_id,
        cycle_id=cycle_id,
    )

    # Extract just the added block for result
    added_block = extract_augmentation(augmented) or ""

    if not dry_run:
        document_path.write_text(augmented)
        logger.info(
            f"Augmented {document_path}: {wiki_count} wikilinks, {action_count} action links"
        )
    else:
        logger.info(
            f"[dry-run] Would augment {document_path}: {wiki_count} wikilinks, {action_count} action links"
        )

    return AugmentationResult(
        document_path=document_path,
        augmentation_type="mixed" if (wikilinks and action_links) else ("wikilink" if wikilinks else "action_search"),
        content_added=added_block,
        slice_id=slice_id,
        cycle_id=cycle_id,
        wikilinks_added=wiki_count,
        action_links_added=action_count,
    )
