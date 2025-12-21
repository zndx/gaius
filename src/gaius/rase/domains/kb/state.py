"""KBState - System state model for Knowledge Base domain.

Implements the SystemState protocol for KB operations, enabling
constraint-based verification of KB documents.

The KB state represents a snapshot of:
- Document content and structure
- Wikilinks between documents
- Citations and external references
- Frontmatter metadata

This state serves as ground truth for intrinsic verification,
following the API-as-oracle pattern where the KB itself is the oracle.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from gaius.rase.traceability import IdScheme, TraceableId


class Citation(BaseModel):
    """A citation or external reference in a KB document.

    Attributes:
        url: The URL or URI of the citation
        text: The anchor text or citation label
        line_number: Line number where citation appears
        accessible: Whether the URL was verified accessible (None = not checked)
    """

    url: str
    text: str = ""
    line_number: int = 0
    accessible: bool | None = None

    model_config = {"frozen": True}


class KBLink(BaseModel):
    """A wikilink between KB documents.

    Attributes:
        target: The link target (e.g., "current/topics/kudu")
        text: The display text (if different from target)
        line_number: Line number where link appears
        resolved: Whether the target document exists (None = not checked)
    """

    target: str
    text: str = ""
    line_number: int = 0
    resolved: bool | None = None

    model_config = {"frozen": True}


class KBDocument(BaseModel):
    """A document in the Knowledge Base.

    Represents the parsed state of a single KB document,
    including its content, metadata, and links.

    Attributes:
        path: Relative path from KB root
        content: Raw markdown content
        frontmatter: Parsed YAML frontmatter (if present)
        body: Content without frontmatter
        wikilinks: Extracted [[wikilinks]]
        citations: Extracted [citations](url) and bare URLs
        word_count: Number of words in body
        is_valid_markdown: Whether content parses as valid markdown
    """

    path: str
    content: str
    frontmatter: dict[str, Any] = Field(default_factory=dict)
    body: str = ""
    wikilinks: list[KBLink] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    word_count: int = 0
    is_valid_markdown: bool = True
    parse_error: str | None = None

    model_config = {"frozen": True}

    @classmethod
    def from_content(cls, path: str, content: str) -> "KBDocument":
        """Parse a document from its content.

        Extracts frontmatter, wikilinks, citations, and validates structure.
        """
        from gaius.storage.filesystem import parse_frontmatter

        # Parse frontmatter
        try:
            frontmatter, body = parse_frontmatter(content)
        except Exception as e:
            return cls(
                path=path,
                content=content,
                is_valid_markdown=False,
                parse_error=str(e),
            )

        # Extract wikilinks: [[target]] or [[target|text]]
        wikilinks = []
        wikilink_pattern = re.compile(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]")
        for line_num, line in enumerate(body.split("\n"), 1):
            for match in wikilink_pattern.finditer(line):
                target = match.group(1).strip()
                text = match.group(2).strip() if match.group(2) else target
                wikilinks.append(KBLink(
                    target=target,
                    text=text,
                    line_number=line_num,
                ))

        # Extract citations: [text](url) and bare URLs
        citations = []
        # Markdown links
        link_pattern = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
        for line_num, line in enumerate(body.split("\n"), 1):
            for match in link_pattern.finditer(line):
                text = match.group(1).strip()
                url = match.group(2).strip()
                if url.startswith("http://") or url.startswith("https://"):
                    citations.append(Citation(
                        url=url,
                        text=text,
                        line_number=line_num,
                    ))

        # Bare URLs
        url_pattern = re.compile(r"(?<!\()https?://[^\s\)]+")
        for line_num, line in enumerate(body.split("\n"), 1):
            for match in url_pattern.finditer(line):
                url = match.group(0).rstrip(".,;:!?")
                citations.append(Citation(
                    url=url,
                    line_number=line_num,
                ))

        # Word count
        words = body.split()
        word_count = len(words)

        return cls(
            path=path,
            content=content,
            frontmatter=frontmatter,
            body=body,
            wikilinks=wikilinks,
            citations=citations,
            word_count=word_count,
            is_valid_markdown=True,
        )

    def to_traceable_id(self) -> TraceableId:
        """Generate TraceableId for this document."""
        return TraceableId(
            scheme=IdScheme.RASE,
            path=f"kb/{self.path}",
        )


class KBState(BaseModel):
    """State snapshot of the Knowledge Base.

    Implements the SystemState protocol for KB verification.
    Represents the current state of the KB including documents,
    their relationships, and verification status.

    Attributes:
        kb_root: Root directory of the KB
        documents: Dict of path -> KBDocument
        captured_at: When this snapshot was taken
    """

    kb_root: str
    documents: dict[str, KBDocument] = Field(default_factory=dict)
    captured_at: datetime = Field(default_factory=datetime.now)

    def is_stale(self, max_age_seconds: float = 60.0) -> bool:
        """Check if this snapshot is older than max_age_seconds."""
        age = (datetime.now() - self.captured_at).total_seconds()
        return age > max_age_seconds

    def to_traceable_id(self) -> TraceableId:
        """Generate TraceableId for this KB snapshot."""
        timestamp = self.captured_at.strftime("%Y%m%d_%H%M%S")
        return TraceableId(
            scheme=IdScheme.RASE,
            path=f"kb/snapshot/{timestamp}",
        )

    def get_component(self, path: str) -> Any | None:
        """Navigate to a document by path.

        Args:
            path: Document path (e.g., "current/objectives/rsv.md")

        Returns:
            KBDocument if found, None otherwise
        """
        return self.documents.get(path)

    def get_document(self, path: str) -> KBDocument | None:
        """Get a document by path (alias for get_component)."""
        return self.documents.get(path)

    def add_document(self, doc: KBDocument) -> "KBState":
        """Add a document to the state (returns new state)."""
        new_docs = dict(self.documents)
        new_docs[doc.path] = doc
        return KBState(
            kb_root=self.kb_root,
            documents=new_docs,
            captured_at=self.captured_at,
        )

    def document_exists(self, path: str) -> bool:
        """Check if a document exists at the given path."""
        if path in self.documents:
            return True
        # Also check filesystem
        full_path = Path(self.kb_root) / path
        if not full_path.suffix:
            full_path = full_path.with_suffix(".md")
        return full_path.exists()

    def list_documents(self, prefix: str = "") -> list[str]:
        """List document paths with optional prefix filter."""
        return [
            path for path in self.documents.keys()
            if path.startswith(prefix)
        ]

    @classmethod
    def capture(cls, kb_root: str, paths: list[str] | None = None) -> "KBState":
        """Capture current KB state from filesystem.

        Args:
            kb_root: Root directory of the KB
            paths: Optional list of specific paths to capture.
                   If None, captures all .md files.

        Returns:
            KBState snapshot
        """
        kb_path = Path(kb_root)
        documents = {}

        if paths is None:
            # Capture all markdown files
            for md_file in kb_path.rglob("*.md"):
                rel_path = str(md_file.relative_to(kb_path))
                content = md_file.read_text()
                documents[rel_path] = KBDocument.from_content(rel_path, content)
        else:
            # Capture specific paths
            for path in paths:
                full_path = kb_path / path
                if not full_path.suffix:
                    full_path = full_path.with_suffix(".md")
                if full_path.exists():
                    rel_path = str(full_path.relative_to(kb_path))
                    content = full_path.read_text()
                    documents[rel_path] = KBDocument.from_content(rel_path, content)

        return cls(
            kb_root=kb_root,
            documents=documents,
            captured_at=datetime.now(),
        )


__all__ = [
    "Citation",
    "KBLink",
    "KBDocument",
    "KBState",
]
