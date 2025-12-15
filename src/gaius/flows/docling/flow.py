"""ArxivDoclingFlow - Fetch arXiv paper, convert PDF to markdown, save to KB.

This flow demonstrates Metaflow integration with Gaius:
1. Parse arXiv URL and fetch metadata
2. Download PDF from arXiv
3. Optionally archive PDF to KB attachments
4. Use docling to convert PDF to markdown
5. Create zettelkasten note in KB with full lineage

Usage:
    # Local execution (requires devenv postgres/minio)
    python -m gaius.flows.docling.flow run --arxiv_url "https://arxiv.org/abs/2312.12345"

    # K8s execution (via Argo Workflows)
    python -m gaius.flows.docling.flow argo-workflows create --arxiv_url "..."

    # Via CLI
    uv run gaius-cli --cmd "/flow run docling https://arxiv.org/abs/2312.12345"
"""

from __future__ import annotations

import io
import logging
import os
import re
import tempfile
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode

from metaflow import FlowSpec, Parameter, current, kubernetes, retry, step

from gaius.flows import register_flow
from gaius.flows.base import GaiusFlow, get_current_quarter, safe_filename
from gaius.flows.config import apply_metaflow_config

logger = logging.getLogger(__name__)


def extract_arxiv_id(url_or_id: str) -> str | None:
    """Extract arXiv ID from URL or ID string.

    Examples:
        https://arxiv.org/abs/2312.12345 -> 2312.12345
        https://arxiv.org/pdf/2312.12345.pdf -> 2312.12345
        2312.12345 -> 2312.12345
    """
    # New-style IDs: YYMM.NNNNN
    match = re.search(r"(\d{4}\.\d{4,5})", url_or_id)
    if match:
        return match.group(1)

    # Old-style IDs: archive/YYMMNNN
    match = re.search(r"([a-z-]+/\d{7})", url_or_id)
    if match:
        return match.group(1)

    return None


@register_flow("docling")
class ArxivDoclingFlow(GaiusFlow):
    """Fetch arXiv paper, convert PDF to markdown, save to KB.

    Tracks full lineage: arXiv URL → PDF → markdown → KB zettelkasten
    """

    arxiv_url = Parameter(
        "arxiv_url",
        help="arXiv abstract URL (e.g., https://arxiv.org/abs/2312.12345)",
        required=True,
    )

    archive_pdf = Parameter(
        "archive_pdf",
        help="Whether to save PDF to KB archive",
        default=True,
        type=bool,
    )

    @step
    def start(self):
        """Parse arXiv URL and fetch paper metadata."""
        import feedparser
        import httpx

        # Extract arXiv ID
        self.arxiv_id = extract_arxiv_id(self.arxiv_url)
        if not self.arxiv_id:
            raise ValueError(f"Could not extract arXiv ID from: {self.arxiv_url}")

        print(f"Processing arXiv paper: {self.arxiv_id}")

        # Fetch metadata from arXiv API
        api_url = "https://export.arxiv.org/api/query"
        params = {"id_list": self.arxiv_id, "max_results": 1}
        url = f"{api_url}?{urlencode(params)}"

        with httpx.Client(timeout=30.0) as client:
            response = client.get(url)
            response.raise_for_status()

        feed = feedparser.parse(response.text)
        if not feed.entries:
            raise ValueError(f"No paper found for arXiv ID: {self.arxiv_id}")

        entry = feed.entries[0]

        # Extract metadata
        self.title = entry.get("title", "").replace("\n", " ").strip()
        self.abstract = entry.get("summary", "").strip()
        self.authors = [a.get("name", "") for a in entry.get("authors", [])]

        # Get PDF URL
        self.pdf_url = None
        for link in entry.get("links", []):
            if link.get("type") == "application/pdf":
                self.pdf_url = link.get("href")
                break

        if not self.pdf_url:
            self.pdf_url = f"https://arxiv.org/pdf/{self.arxiv_id}.pdf"

        # Extract categories
        self.categories = [tag.get("term", "") for tag in entry.get("tags", [])]

        # Parse published date
        self.published_at = None
        published_str = entry.get("published", "")
        if published_str:
            try:
                self.published_at = datetime.fromisoformat(
                    published_str.replace("Z", "+00:00")
                ).isoformat()
            except ValueError:
                pass

        print(f"Title: {self.title}")
        print(f"Authors: {', '.join(self.authors[:3])}{'...' if len(self.authors) > 3 else ''}")
        print(f"PDF URL: {self.pdf_url}")

        # Emit lineage START
        from gaius.hx.lineage.events import Dataset

        self.emit_lineage_start(
            job_name="arxiv_docling",
            inputs=[Dataset.from_source(self.arxiv_id, "arxiv")],
        )

        self.next(self.fetch_pdf)

    @retry(times=3)
    @step
    def fetch_pdf(self):
        """Download PDF from arXiv."""
        import httpx

        print(f"Downloading PDF from {self.pdf_url}...")

        with httpx.Client(timeout=120.0, follow_redirects=True) as client:
            response = client.get(self.pdf_url)
            response.raise_for_status()

        self.pdf_bytes = response.content
        self.pdf_size = len(self.pdf_bytes)

        print(f"Downloaded {self.pdf_size:,} bytes")

        self.next(self.archive_step)

    @step
    def archive_step(self):
        """Optionally save PDF to KB archive."""
        self.archive_path_result = None

        if self.archive_pdf:
            # Generate archive path
            quarter = get_current_quarter()
            pdf_filename = f"{self.arxiv_id.replace('/', '_')}.pdf"
            self.archive_path_result = f"current/archive/{quarter}/attachments/{pdf_filename}"

            # Save to KB
            kb_root = Path(os.environ.get("GAIUS_KB_ROOT", "build/dev"))
            full_path = kb_root / self.archive_path_result
            full_path.parent.mkdir(parents=True, exist_ok=True)

            with open(full_path, "wb") as f:
                f.write(self.pdf_bytes)

            print(f"Archived PDF to: {self.archive_path_result}")

        self.next(self.convert_to_markdown)

    # Note: @kubernetes decorator would be used for K8s execution
    # @kubernetes(cpu=2, memory=4096)
    @step
    def convert_to_markdown(self):
        """Use docling to convert PDF to markdown."""
        from docling.document_converter import DocumentConverter

        print("Converting PDF to markdown with docling...")

        # Write PDF to temp file (docling needs file path)
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(self.pdf_bytes)
            temp_pdf_path = f.name

        try:
            # Convert with docling
            converter = DocumentConverter()
            result = converter.convert(temp_pdf_path)

            # Export to markdown
            self.markdown = result.document.export_to_markdown()

            print(f"Extracted {len(self.markdown):,} characters of markdown")

        finally:
            # Clean up temp file
            Path(temp_pdf_path).unlink(missing_ok=True)

        self.next(self.create_zettelkasten)

    @step
    def create_zettelkasten(self):
        """Create KB note with YAML frontmatter."""
        now = datetime.now()
        date_str = now.strftime("%Y-%m-%d")
        time_str = now.strftime("%H%M%S")

        # Generate KB path
        safe_title = safe_filename(self.title)
        filename = f"{time_str}_arxiv_{safe_title}.md"
        self.kb_path = f"scratch/{date_str}/{filename}"

        # Format frontmatter
        frontmatter_lines = [
            "---",
            f"title: \"{self.title}\"",
            f"created: {now.isoformat()}",
            "type: research",
            f"source: arXiv",
            f"arxiv_id: \"{self.arxiv_id}\"",
            f"arxiv_url: \"https://arxiv.org/abs/{self.arxiv_id}\"",
            f"pdf_url: \"{self.pdf_url}\"",
        ]

        if self.authors:
            authors_str = ", ".join(f'"{a}"' for a in self.authors[:5])
            frontmatter_lines.append(f"authors: [{authors_str}]")

        if self.categories:
            cats_str = ", ".join(f'"{c}"' for c in self.categories[:5])
            frontmatter_lines.append(f"categories: [{cats_str}]")

        if self.published_at:
            frontmatter_lines.append(f"published: \"{self.published_at}\"")

        if self.archive_path_result:
            frontmatter_lines.append(f"pdf_archive: \"{self.archive_path_result}\"")

        frontmatter_lines.append("---")
        frontmatter = "\n".join(frontmatter_lines)

        # Compose full document
        self.document = f"""{frontmatter}

# {self.title}

## Abstract

{self.abstract}

## Extracted Content

{self.markdown}

---
*Extracted from arXiv:{self.arxiv_id} using docling*
"""

        # Write to KB
        kb_root = Path(os.environ.get("GAIUS_KB_ROOT", "build/dev"))
        full_path = kb_root / self.kb_path
        full_path.parent.mkdir(parents=True, exist_ok=True)

        with open(full_path, "w") as f:
            f.write(self.document)

        print(f"Created zettelkasten note: {self.kb_path}")

        self.next(self.end)

    @step
    def end(self):
        """Emit final lineage and report results."""
        from gaius.hx.lineage.events import Dataset

        # Collect outputs
        outputs = [Dataset.from_kb(self.kb_path)]
        if self.archive_path_result:
            outputs.append(Dataset.from_kb(self.archive_path_result))

        # Emit lineage COMPLETE
        self.emit_lineage_complete(outputs)

        # Summary
        print("")
        print("=" * 60)
        print("  ArxivDoclingFlow Complete")
        print("=" * 60)
        print(f"  arXiv ID:      {self.arxiv_id}")
        print(f"  Title:         {self.title[:50]}...")
        print(f"  KB Note:       {self.kb_path}")
        if self.archive_path_result:
            print(f"  PDF Archive:   {self.archive_path_result}")
        print(f"  Markdown:      {len(self.markdown):,} characters")
        print("")
        print(f"  Lineage: arXiv:{self.arxiv_id} → {self.kb_path}")
        print("=" * 60)


if __name__ == "__main__":
    # Apply Metaflow config before running
    apply_metaflow_config("local")
    ArxivDoclingFlow()
