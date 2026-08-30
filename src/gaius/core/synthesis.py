"""Zettelkasten synthesis from search results.

Takes hybrid search results (BM25 + Vector + Web) and generates
a structured Zettelkasten note with proper citations.

Usage:
    synthesizer = ZettelkastenSynthesizer()
    note = await synthesizer.synthesize(
        query="distributed consensus",
        kb_results=[...],
        web_results=[...],
    )
    note.save()
"""

import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass
class Citation:
    """A citation to a source document."""

    path: str  # KB path or URL
    title: str
    snippet: str
    pattern: str | None = None  # Regex pattern for KB citations
    is_web: bool = False

    def to_markdown(self) -> str:
        """Format as markdown citation."""
        if self.is_web:
            return f"[{self.title}]({self.path})"
        elif self.pattern:
            return f"[{self.title}]({self.path}:/{self.pattern}/)"
        else:
            return f"[{self.title}]({self.path})"

    def verify(self, kb_root: Path) -> bool:
        """Verify KB citation exists."""
        if self.is_web:
            return True  # Can't verify web citations offline

        full_path = kb_root / self.path
        if not full_path.exists():
            return False

        if self.pattern:
            try:
                content = full_path.read_text()
                return bool(re.search(self.pattern, content))
            except Exception:
                return False

        return True


@dataclass
class ZettelkastenNote:
    """A synthesized Zettelkasten note."""

    query: str
    content: str
    citations: list[Citation] = field(default_factory=list)
    wiki_links: list[str] = field(default_factory=list)  # [[topic]] links (normalized)
    created_at: datetime = field(default_factory=datetime.now)
    metadata: dict[str, Any] = field(default_factory=dict)
    origin_file: str | None = None  # Source file that triggered resolution (for backlink)
    resolved_from: str | None = None  # Original wiki link text that was resolved

    def to_markdown(self) -> str:
        """Generate full markdown document."""
        # Normalize query to skewer-case for title
        title = self.query

        lines = [
            f"# {title}",
            "",
            "---",
            f"created: {self.created_at.isoformat()}",
            f"type: zettel",
            f"sources: {len(self.citations)}",
        ]

        if self.wiki_links:
            # Links are already normalized to skewer-case
            # Format: [[link]] -> current/topics/link.md
            links_str = ", ".join(f"[[{l}]]" for l in self.wiki_links)
            lines.append(f"links: {links_str}")
            # Also add link targets for clarity
            targets = [f"current/topics/{l}.md" for l in self.wiki_links]
            lines.append(f"link-targets: {', '.join(targets)}")

        # Add origin backlink if this note was created from resolving a broken link
        if self.origin_file:
            # Extract stem for wiki link (remove .md extension and path)
            origin_stem = Path(self.origin_file).stem
            lines.append(f"origin: [[{origin_stem}]]")
        if self.resolved_from:
            lines.append(f"resolved-from: {self.resolved_from}")

        lines.extend([
            "---",
            "",
            self.content,
            "",
            "---",
            "",
            "## Sources",
            "",
        ])

        # KB sources
        kb_citations = [c for c in self.citations if not c.is_web]
        if kb_citations:
            lines.append("### Knowledge Base")
            lines.append("")
            for c in kb_citations:
                lines.append(f"- {c.to_markdown()}")
                if c.snippet:
                    # Indent snippet as quote
                    snippet = c.snippet[:150].replace("\n", " ")
                    lines.append(f"  > {snippet}...")
            lines.append("")

        # Web sources
        web_citations = [c for c in self.citations if c.is_web]
        if web_citations:
            lines.append("### Web")
            lines.append("")
            for c in web_citations:
                lines.append(f"- {c.to_markdown()}")
            lines.append("")

        return "\n".join(lines)

    def save(self, kb_root: Path | str | None = None) -> Path:
        """Save note to KB scratch directory."""
        if kb_root is None:
            kb_root = Path(os.getenv("GAIUS_KB_ROOT", "build/dev"))
        kb_root = Path(kb_root)

        today = self.created_at.strftime("%Y-%m-%d")
        timestamp = self.created_at.strftime("%H%M%S")
        safe_query = re.sub(r"[^\w\s-]", "", self.query.lower())
        safe_query = re.sub(r"[-\s]+", "-", safe_query)[:50].strip("-")

        path = kb_root / "scratch" / today / f"{timestamp}_{safe_query}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.to_markdown())

        return path


# System prompt for Zettelkasten synthesis
SYNTHESIS_PROMPT = """You are a research assistant creating Zettelkasten notes.

Given search results from a knowledge base and web sources, synthesize a clear,
structured note that:

1. Answers the query directly and concisely
2. Integrates information from multiple sources
3. Uses wiki-style [[links]] for key concepts that could have their own notes
4. Maintains academic rigor with proper attribution

Format guidelines:
- Start with a clear summary paragraph
- Use headers (##) to organize sections if needed
- Use [[concept]] syntax for important terms that deserve their own notes
- Be concise but thorough
- Focus on synthesizing, not just summarizing

Do NOT include a sources section - that will be added automatically."""


class ZettelkastenSynthesizer:
    """Synthesizes Zettelkasten notes from search results."""

    def __init__(self, kb_root: Path | str | None = None):
        if kb_root is None:
            kb_root = Path(os.getenv("GAIUS_KB_ROOT", "build/dev"))
        self.kb_root = Path(kb_root)

    async def synthesize(
        self,
        query: str,
        kb_results: list[dict],
        web_results: list[dict],
        domain: str | None = None,
    ) -> ZettelkastenNote:
        """Synthesize a Zettelkasten note from search results.

        Args:
            query: The search query
            kb_results: Results from hybrid KB search (BM25 + Vector)
            web_results: Results from web search
            domain: Optional domain context

        Returns:
            ZettelkastenNote ready to save
        """
        from gaius.client import get_grpc_client

        # Build context from results
        context_parts = []

        if kb_results:
            context_parts.append("## Knowledge Base Results\n")
            for i, r in enumerate(kb_results[:10], 1):
                title = r.get("title", "Untitled")
                snippet = r.get("snippet", "")[:300]
                source = r.get("source", "kb")
                context_parts.append(f"{i}. **{title}** [{source}]\n   {snippet}\n")

        if web_results:
            context_parts.append("\n## Web Results\n")
            for i, r in enumerate(web_results[:5], 1):
                title = r.get("title", "Untitled")
                snippet = r.get("snippet", "")[:200]
                context_parts.append(f"{i}. **{title}**\n   {snippet}\n")

        context = "\n".join(context_parts)

        # Build system prompt
        system = SYNTHESIS_PROMPT
        if domain:
            system += f"\n\nDomain context: {domain}"

        # Generate synthesis via gRPC
        client = await get_grpc_client()
        result = await client.call(
            service="Scheduler",
            action="complete",
            params={
                "prompt": f"Query: {query}\n\n{context}\n\nSynthesize a Zettelkasten note.",
                "system_prompt": system,
                "agent": "thinking",
                "technique": "cot_reflection",
            },
        )
        # gRPC CompleteResponse uses the 'text' field
        result_content = result.get("text", result.get("content", ""))

        # Extract and normalize wiki links from generated content
        wiki_links = self._extract_wiki_links(result_content)

        # Normalize links in the content itself
        normalized_content = self._normalize_content_links(result_content)

        # Build citations
        citations = []
        for r in kb_results[:10]:
            citations.append(Citation(
                path=r.get("path", ""),
                title=r.get("title", "Untitled"),
                snippet=r.get("snippet", ""),
                pattern=self._extract_pattern(r.get("citation", "")),
                is_web=False,
            ))

        for r in web_results[:5]:
            citations.append(Citation(
                path=r.get("url", ""),
                title=r.get("title", "Untitled"),
                snippet=r.get("snippet", ""),
                is_web=True,
            ))

        return ZettelkastenNote(
            query=query,
            content=normalized_content,
            citations=citations,
            wiki_links=wiki_links,
            metadata={
                "model": result.get("model", ""),
                "technique": "cot_reflection",
                "tokens": f"{result.get('input_tokens', 0)}+{result.get('tokens_used', result.get('output_tokens', 0))}",
                "domain": domain,
            },
        )

    def _extract_wiki_links(self, content: str) -> list[str]:
        """Extract [[wiki-style]] links from content and normalize to skewer-case."""
        pattern = r"\[\[([^\]]+)\]\]"
        matches = re.findall(pattern, content)
        # Deduplicate while preserving order, normalize to skewer-case
        seen = set()
        result = []
        for m in matches:
            normalized = self._normalize_link(m)
            if normalized not in seen:
                seen.add(normalized)
                result.append(normalized)
        return result

    def _normalize_link(self, link: str) -> str:
        """Normalize a wiki link to proper case convention.

        Conventions:
        - skewer-case preferred: distributed-systems
        - underscores for combining topics: consensus_algorithms
        - CamelCase for persons: JohnSmith
        - No spaces ever
        """
        link = link.strip()

        # Check if it looks like a person name (two+ capitalized words)
        words = link.split()
        if len(words) >= 2 and all(w[0].isupper() for w in words if w):
            # Likely a person - use CamelCase
            return "".join(w.capitalize() for w in words)

        # Default: skewer-case
        # Replace spaces with hyphens, lowercase
        normalized = re.sub(r"\s+", "-", link.lower())
        # Remove any non-alphanumeric except hyphens and underscores
        normalized = re.sub(r"[^a-z0-9\-_]", "", normalized)
        # Collapse multiple hyphens
        normalized = re.sub(r"-+", "-", normalized)
        return normalized.strip("-")

    def _normalize_content_links(self, content: str) -> str:
        """Replace wiki links in content with normalized versions."""
        def replace_link(match):
            original = match.group(1)
            normalized = self._normalize_link(original)
            return f"[[{normalized}]]"

        return re.sub(r"\[\[([^\]]+)\]\]", replace_link, content)

    def _extract_pattern(self, citation: str) -> str | None:
        """Extract regex pattern from citation string."""
        # Citation format: path:/pattern/
        match = re.search(r":/(.*?)/$", citation)
        if match:
            return match.group(1)
        return None

    def verify_citations(self, note: ZettelkastenNote) -> dict[str, bool]:
        """Verify all KB citations in a note."""
        results = {}
        for c in note.citations:
            if not c.is_web:
                results[c.path] = c.verify(self.kb_root)
        return results


# Module-level helper
async def synthesize_search(
    query: str,
    kb_results: list[dict],
    web_results: list[dict],
    domain: str | None = None,
    save: bool = True,
) -> ZettelkastenNote:
    """Convenience function to synthesize and optionally save a note."""
    synthesizer = ZettelkastenSynthesizer()
    note = await synthesizer.synthesize(query, kb_results, web_results, domain)

    if save:
        note.save()

    return note
