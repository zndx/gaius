"""Wiki-link parsing and graph management."""

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator


# Pattern to match [[path]] wiki-links
WIKILINK_PATTERN = re.compile(r'\[\[([^\]]+)\]\]')


def parse_wikilinks(text: str) -> list[str]:
    """Extract all wiki-link paths from text.

    Args:
        text: Markdown text containing [[path]] links

    Returns:
        List of link paths (without brackets)
    """
    return WIKILINK_PATTERN.findall(text)


def iter_wikilinks(text: str) -> Iterator[tuple[int, int, str]]:
    """Iterate over wiki-links with their positions.

    Yields:
        (start, end, path) tuples for each link
    """
    for match in WIKILINK_PATTERN.finditer(text):
        yield match.start(), match.end(), match.group(1)


@dataclass
class LinkGraph:
    """Bidirectional graph of wiki-links between files.

    Tracks both forward links (what a file links to) and
    backlinks (what files link to a given file).
    """

    # Forward links: source path -> set of target paths
    forward: dict[str, set[str]] = field(default_factory=dict)

    # Backlinks: target path -> set of source paths
    back: dict[str, set[str]] = field(default_factory=dict)

    def add_link(self, source: str, target: str) -> None:
        """Add a link from source to target."""
        if source not in self.forward:
            self.forward[source] = set()
        self.forward[source].add(target)

        if target not in self.back:
            self.back[target] = set()
        self.back[target].add(source)

    def remove_link(self, source: str, target: str) -> None:
        """Remove a link from source to target."""
        if source in self.forward:
            self.forward[source].discard(target)
        if target in self.back:
            self.back[target].discard(source)

    def update_file(self, filepath: str, text: str, kb_root: Path) -> None:
        """Update graph with links from a file.

        Parses the file text for wiki-links and updates the graph.
        """
        # Remove old links from this file
        old_targets = self.forward.get(filepath, set()).copy()
        for target in old_targets:
            self.remove_link(filepath, target)

        # Add new links
        for link_path in parse_wikilinks(text):
            # Resolve to absolute path
            target = str(kb_root / f"{link_path}.md")
            self.add_link(filepath, target)

    def get_links(self, filepath: str) -> set[str]:
        """Get all files that this file links to."""
        return self.forward.get(filepath, set())

    def get_backlinks(self, filepath: str) -> set[str]:
        """Get all files that link to this file."""
        return self.back.get(filepath, set())

    def save(self, path: Path) -> None:
        """Save graph to JSON file."""
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "forward": {k: list(v) for k, v in self.forward.items()},
            "back": {k: list(v) for k, v in self.back.items()},
        }
        path.write_text(json.dumps(data, indent=2))

    @classmethod
    def load(cls, path: Path) -> "LinkGraph":
        """Load graph from JSON file."""
        if not path.exists():
            return cls()
        try:
            data = json.loads(path.read_text())
            return cls(
                forward={k: set(v) for k, v in data.get("forward", {}).items()},
                back={k: set(v) for k, v in data.get("back", {}).items()},
            )
        except (json.JSONDecodeError, KeyError):
            return cls()


def resolve_link(link_path: str, kb_root: Path) -> tuple[Path, bool]:
    """Resolve a wiki-link path to a file path.

    Args:
        link_path: The path from [[path]] (without .md extension)
        kb_root: Root directory of the KB (e.g., build/dev)

    Returns:
        (resolved_path, exists) tuple
    """
    # Add .md extension if not present
    if not link_path.endswith(".md"):
        link_path = f"{link_path}.md"

    resolved = kb_root / link_path
    return resolved, resolved.exists()


def create_linked_file(
    link_path: str,
    kb_root: Path,
    source_file: str | None = None,
) -> Path:
    """Create a new file from a wiki-link.

    Args:
        link_path: The path from [[path]]
        kb_root: Root directory of the KB
        source_file: Optional path of the file containing the link

    Returns:
        Path to the created file
    """
    from datetime import datetime

    resolved, exists = resolve_link(link_path, kb_root)

    if exists:
        return resolved

    # Create parent directories
    resolved.parent.mkdir(parents=True, exist_ok=True)

    # Generate title from path
    title = resolved.stem.replace("-", " ").replace("_", " ").title()

    # Build template
    lines = [
        f"# {title}",
        "",
        f"Created: {datetime.now().isoformat()}",
    ]

    if source_file:
        # Add backlink to source
        source_rel = Path(source_file).stem
        lines.append(f"Linked from: [[{source_rel}]]")

    lines.extend(["", "---", "", ""])

    resolved.write_text("\n".join(lines))
    return resolved
