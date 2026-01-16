"""ArxivDoclingFlow - Fetch arXiv paper, convert PDF to markdown, save to KB.

This flow demonstrates Metaflow integration with Gaius:
1. Parse arXiv URL and fetch metadata
2. Download PDF from arXiv
3. Optionally archive PDF to KB attachments
4. Use docling to convert PDF to markdown
5. Score paper relevance using LLM with rubric
6. Extract topics using LDA/LSA/HDP/BERTopic
7. Create zettelkasten note in KB with full lineage

Topic modeling:
- Supports Gensim (LDA, LSA, HDP) and BERTopic
- HDP and BERTopic auto-discover optimal topic count
- Generates visual Metaflow cards with topic distributions

OpenTelemetry Integration:
- Inherits from TracedFlow for automatic span creation
- Emits semantic events for key operations (pdf.extraction, topics.extracted, etc.)
- correlation_id links Metaflow execution to NiFi FlowFiles

Usage:
    # Local execution (requires devenv postgres/minio)
    python -m gaius.flows.docling.flow run --arxiv_url "https://arxiv.org/abs/2312.12345"

    # With topic modeling
    python -m gaius.flows.docling.flow run --arxiv_url "..." --enable_topics True --topic_model_type bertopic

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

from metaflow import FlowSpec, Parameter, card, current, kubernetes, retry, step
from metaflow.cards import Markdown, Table, Image

from gaius.agents.metaagent.telemetry import TracedFlow, traced_step
from gaius.agents.metaagent.telemetry.attributes import EventNames
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
class ArxivDoclingFlow(TracedFlow, GaiusFlow):
    """Fetch arXiv paper, convert PDF to markdown, save to KB.

    Tracks full lineage: arXiv URL → PDF → markdown → KB zettelkasten

    OTel Integration:
        - Inherits from TracedFlow for automatic span creation per step
        - Emits semantic events: pdf.extraction.*, topics.extracted, scoring.completed
        - correlation_id links this run to NiFi FlowFiles for end-to-end tracing
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

    # Topic modeling parameters
    enable_topics = Parameter(
        "enable_topics",
        help="Enable topic extraction (requires 5+ docs in corpus)",
        default=True,
        type=bool,
    )

    topic_model_type = Parameter(
        "topic_model_type",
        help="Topic model type: lda, lsa, hdp, bertopic",
        default="bertopic",
    )

    num_topics = Parameter(
        "num_topics",
        help="Number of topics (ignored for hdp/bertopic which auto-discover)",
        default=None,
        type=int,
    )

    # Scoring parameters
    enable_scoring = Parameter(
        "enable_scoring",
        help="Enable LLM-based relevance scoring",
        default=True,
        type=bool,
    )

    scoring_rubric = Parameter(
        "scoring_rubric",
        help="Scoring rubric name (from config/scoring_rubrics/)",
        default="default",
    )

    use_remote_scoring = Parameter(
        "use_remote_scoring",
        help="Use remote model for scoring calibration",
        default=False,
        type=bool,
    )

    @traced_step
    @step
    def start(self):
        """Parse arXiv URL and fetch paper metadata."""
        import feedparser
        import httpx

        # Emit semantic event for paper processing start
        self.emit_event("paper.processing.started", {
            "arxiv_url": self.arxiv_url,
            "correlation_id": self.correlation_id,
        })

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

    @traced_step
    @retry(times=3)
    @step
    def fetch_pdf(self):
        """Download PDF from arXiv."""
        import httpx

        if self.pdf_url is None:
            raise RuntimeError(
                f"PDF URL not resolved for {self.arxiv_id}.\n"
                "  Guru Meditation: #DOCLING.00000001.NO_PDF_URL\n"
                "  The arXiv page did not yield a PDF link."
            )
        pdf_url = self.pdf_url  # narrowed to str

        self.emit_event(EventNames.PDF_EXTRACTION_STARTED, {
            "arxiv_id": self.arxiv_id,
            "pdf_url": pdf_url,
        })

        print(f"Downloading PDF from {pdf_url}...")

        with httpx.Client(timeout=120.0, follow_redirects=True) as client:
            response = client.get(pdf_url)
            response.raise_for_status()

        self.pdf_bytes = response.content
        self.pdf_size = len(self.pdf_bytes)

        self.emit_event(EventNames.PDF_EXTRACTION_COMPLETED, {
            "arxiv_id": self.arxiv_id,
            "pdf_size_bytes": self.pdf_size,
        })

        print(f"Downloaded {self.pdf_size:,} bytes")

        self.next(self.archive_step)

    @traced_step
    @step
    def archive_step(self):
        """Optionally save PDF to KB archive."""
        self.archive_path_result = None

        if self.archive_pdf:
            if self.arxiv_id is None:
                raise RuntimeError(
                    "arxiv_id not set in archive_step.\n"
                    "  Guru Meditation: #DOCLING.00000002.NO_ARXIV_ID\n"
                    "  The start step should have set this."
                )
            arxiv_id = self.arxiv_id  # narrowed to str

            # Generate archive path
            quarter = get_current_quarter()
            pdf_filename = f"{arxiv_id.replace('/', '_')}.pdf"
            self.archive_path_result = f"current/archive/{quarter}/attachments/{pdf_filename}"

            # Save to KB
            kb_root = Path(os.environ.get("GAIUS_KB_ROOT", "build/dev"))
            full_path = kb_root / self.archive_path_result
            full_path.parent.mkdir(parents=True, exist_ok=True)

            with open(full_path, "wb") as f:
                f.write(self.pdf_bytes)

            self.emit_event("pdf.archived", {
                "arxiv_id": arxiv_id,
                "archive_path": self.archive_path_result,
            })

            print(f"Archived PDF to: {self.archive_path_result}")

        self.next(self.convert_to_markdown)

    # Note: @kubernetes decorator would be used for K8s execution
    # @kubernetes(cpu=2, memory=4096)
    @traced_step
    @step
    def convert_to_markdown(self):
        """Use docling to convert PDF to markdown."""
        from docling.document_converter import DocumentConverter

        self.emit_event("docling.conversion.started", {
            "arxiv_id": self.arxiv_id,
            "pdf_size_bytes": self.pdf_size,
        })

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

            self.emit_event("docling.conversion.completed", {
                "arxiv_id": self.arxiv_id,
                "markdown_chars": len(self.markdown),
            })

            print(f"Extracted {len(self.markdown):,} characters of markdown")

        finally:
            # Clean up temp file
            Path(temp_pdf_path).unlink(missing_ok=True)

        self.next(self.score_relevance)

    @traced_step
    # Metaflow @card stubs don't include `type` kwarg - see GitHub #15
    @card(type="blank")  # type: ignore[unknown-argument] - Metaflow stubs incomplete, type= is valid
    @step
    def score_relevance(self):
        """Score paper relevance using LLM with rubric."""
        import asyncio

        self.paper_score = None
        self.rubric_version = None

        if not self.enable_scoring:
            print("Scoring disabled, skipping...")
            self.next(self.extract_topics)
            return

        if self.arxiv_id is None:
            raise RuntimeError(
                "arxiv_id not set in score_paper step.\n"
                "  Guru Meditation: #DOCLING.00000003.NO_ARXIV_ID\n"
                "  The start step should have set this."
            )
        arxiv_id = self.arxiv_id  # narrowed to str

        self.emit_event(EventNames.SCORING_STARTED, {
            "arxiv_id": arxiv_id,
            "rubric": self.scoring_rubric,
        })

        try:
            from gaius.flows.topics.scoring import load_rubric, score_paper

            rubric = load_rubric(self.scoring_rubric)
            self.rubric_version = rubric.version

            print(f"Scoring paper with rubric: {rubric.name} v{rubric.version}")

            # Run async scoring in sync context
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                self.paper_score = loop.run_until_complete(
                    score_paper(
                        self.abstract,
                        rubric,
                        arxiv_id=arxiv_id,
                        use_local=True,
                        use_remote=self.use_remote_scoring,
                    )
                )
            finally:
                loop.close()

            self.emit_event(EventNames.SCORING_COMPLETED, {
                "arxiv_id": arxiv_id,
                "overall_score": self.paper_score.overall_score,
                "rubric": self.scoring_rubric,
                "model_used": self.paper_score.model_used,
            })

            print(f"Overall score: {self.paper_score.overall_score:.2f}")
            for name, score in self.paper_score.criteria_scores.items():
                print(f"  {name}: {score:.2f}")

            # Build card content
            current.card.append(Markdown(f"# Paper Relevance Score"))
            current.card.append(Markdown(f"**arXiv ID:** {self.arxiv_id}"))
            current.card.append(Markdown(f"**Title:** {self.title}"))
            current.card.append(Markdown(f"**Overall Score:** {self.paper_score.overall_score:.2%}"))
            current.card.append(Markdown(f"**Rubric:** {rubric.name} v{rubric.version}"))
            current.card.append(Markdown(f"**Model:** {self.paper_score.model_used}"))

            # Criteria table
            rows = [[name, f"{score:.2%}"] for name, score in self.paper_score.criteria_scores.items()]
            current.card.append(Markdown("## Criteria Scores"))
            current.card.append(Table(rows, headers=["Criterion", "Score"]))

            if self.paper_score.reasoning:
                current.card.append(Markdown("## Reasoning"))
                current.card.append(Markdown(self.paper_score.reasoning))

        except Exception as e:
            print(f"Scoring failed: {e}")
            current.card.append(Markdown(f"# Scoring Failed"))
            current.card.append(Markdown(f"Error: {e}"))

        self.next(self.extract_topics)

    @traced_step
    # Metaflow @card stubs don't include `type` kwarg - see GitHub #15
    @card(type="blank")  # type: ignore[unknown-argument] - Metaflow stubs incomplete, type= is valid
    @step
    def extract_topics(self):
        """Extract topics from document using configured model."""
        self.topic_result = None
        self.topic_model_info = None

        if not self.enable_topics:
            print("Topic extraction disabled, skipping...")
            self.next(self.create_zettelkasten)
            return

        self.emit_event("topics.extraction.started", {
            "arxiv_id": self.arxiv_id,
            "model_type": self.topic_model_type,
        })

        try:
            from gaius.flows.topics import (
                CorpusState,
                load_corpus_state,
                tokenize_document,
                train_topic_model,
                get_document_topics,
                save_corpus_state,
            )

            print(f"Extracting topics with {self.topic_model_type}...")

            # Load existing corpus state
            corpus_state = load_corpus_state()

            # Combine abstract and markdown for topic extraction
            full_text = f"{self.abstract}\n\n{self.markdown}"

            # For first few documents, we just accumulate
            # Topic model training requires 5+ documents
            if corpus_state is None:
                doc_count = 0
            else:
                doc_count = corpus_state.document_count

            print(f"Corpus has {doc_count} documents")

            if doc_count >= 4:  # This will be 5th+
                # Load all accumulated documents from KB scratch folder
                documents = [full_text]  # Start with current document

                # Load previous arxiv documents from KB
                try:
                    kb_root = os.environ.get("GAIUS_KB_ROOT", "build/dev")
                    scratch_dir = Path(kb_root) / "scratch"
                    if scratch_dir.exists():
                        for md_file in scratch_dir.rglob("*arxiv*.md"):
                            try:
                                content = md_file.read_text()
                                # Extract main content (skip YAML frontmatter)
                                if "---" in content:
                                    parts = content.split("---", 2)
                                    if len(parts) >= 3:
                                        content = parts[2]
                                if len(content) > 500:  # Skip tiny files
                                    documents.append(content)
                            except Exception:
                                pass
                    print(f"Loaded {len(documents)} documents for topic modeling")
                except Exception as e:
                    print(f"Warning: Could not load KB documents: {e}")

                topic_model = train_topic_model(
                    documents,
                    model_type=self.topic_model_type,
                    num_topics=self.num_topics,
                )

                self.topic_result = get_document_topics(topic_model, full_text)
                self.topic_model_info = {
                    "model_type": topic_model.model_type.value,
                    "num_topics": topic_model.num_topics,
                    "coherence_score": topic_model.coherence_score,
                }

                self.emit_event(EventNames.TOPICS_EXTRACTED, {
                    "arxiv_id": self.arxiv_id,
                    "num_topics": topic_model.num_topics,
                    "model_type": self.topic_model_type,
                    "coherence_score": topic_model.coherence_score,
                })

                print(f"Discovered {topic_model.num_topics} topics")
                print(f"Document topics: {self.topic_result.topics[:3]}")

                # Build card with visualizations
                current.card.append(Markdown(f"# Topic Analysis"))
                current.card.append(Markdown(f"**Model:** {self.topic_model_type.upper()}"))
                current.card.append(Markdown(f"**Topics Discovered:** {topic_model.num_topics}"))

                if topic_model.coherence_score:
                    current.card.append(Markdown(f"**Coherence (C_v):** {topic_model.coherence_score:.4f}"))

                # Topic assignments table
                current.card.append(Markdown("## Document Topic Distribution"))
                rows = []
                for tid, weight in self.topic_result.topics[:5]:
                    words = ", ".join(self.topic_result.top_words.get(tid, [])[:5])
                    rows.append([str(tid), f"{weight:.2%}", words])
                current.card.append(Table(rows, headers=["Topic", "Weight", "Top Words"]))

                # BERTopic visualizations - render as PNG images
                if self.topic_model_type == "bertopic":
                    from metaflow.cards import Image
                    import io

                    # Show all discovered topics with their words
                    current.card.append(Markdown("## All Topics"))
                    all_topics = topic_model.get_all_topics()
                    topic_rows = []
                    for tid, words in sorted(all_topics.items()):
                        topic_rows.append([str(tid), ", ".join(words[:8])])
                    if topic_rows:
                        current.card.append(Table(topic_rows, headers=["Topic ID", "Top Words"]))

                    # Render Plotly figures as PNG images
                    if topic_model.barchart_fig:
                        try:
                            current.card.append(Markdown("## Topic Term Importance"))
                            img_bytes = topic_model.barchart_fig.to_image(
                                format="png", width=900, height=500, scale=2
                            )
                            current.card.append(Image(img_bytes, label="Topic Barchart"))
                            print("Added barchart visualization to card")
                        except Exception as e:
                            print(f"Could not render barchart: {e}")

                    if topic_model.hierarchy_fig:
                        try:
                            current.card.append(Markdown("## Topic Hierarchy"))
                            img_bytes = topic_model.hierarchy_fig.to_image(
                                format="png", width=900, height=600, scale=2
                            )
                            current.card.append(Image(img_bytes, label="Topic Hierarchy"))
                            print("Added hierarchy visualization to card")
                        except Exception as e:
                            print(f"Could not render hierarchy: {e}")

                    if topic_model.similarity_matrix:
                        try:
                            current.card.append(Markdown("## Topic Similarity Heatmap"))
                            img_bytes = topic_model.similarity_matrix.to_image(
                                format="png", width=700, height=700, scale=2
                            )
                            current.card.append(Image(img_bytes, label="Topic Similarity"))
                            print("Added similarity heatmap to card")
                        except Exception as e:
                            print(f"Could not render similarity matrix: {e}")

            else:
                current.card.append(Markdown(f"# Topic Analysis"))
                current.card.append(Markdown(f"**Status:** Accumulating corpus ({doc_count + 1}/5 documents)"))
                current.card.append(Markdown("Topic modeling will begin after 5 documents are processed."))
                print(f"Need {5 - doc_count - 1} more documents for topic modeling")

            # Save updated corpus state with incremented document count
            import uuid
            new_state = CorpusState(
                version_id=str(uuid.uuid4()),
                document_count=doc_count + 1,
                vocabulary_size=0,  # Not tracking vocabulary yet
                model_type=self.topic_model_type,
            )
            save_corpus_state(new_state)
            print(f"Saved corpus state: {doc_count + 1} documents")

        except Exception as e:
            print(f"Topic extraction failed: {e}")
            import traceback
            traceback.print_exc()
            current.card.append(Markdown(f"# Topic Extraction Failed"))
            current.card.append(Markdown(f"Error: {e}"))

        self.next(self.create_zettelkasten)

    @traced_step
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

        # Add scoring metadata
        if self.paper_score:
            frontmatter_lines.append(f"relevance_score: {self.paper_score.overall_score:.3f}")
            frontmatter_lines.append(f"scoring_rubric: \"{self.scoring_rubric}\"")
            frontmatter_lines.append(f"scoring_rubric_version: \"{self.rubric_version}\"")

        # Add topic metadata
        if self.topic_result:
            topic_ids = [str(t[0]) for t, _ in zip(self.topic_result.topics[:3], range(3))]
            frontmatter_lines.append(f"topics: [{', '.join(topic_ids)}]")
            # Get keywords from top topic
            if self.topic_result.topics:
                top_topic_id = self.topic_result.topics[0][0]
                keywords = self.topic_result.top_words.get(top_topic_id, [])[:5]
                if keywords:
                    kw_str = ", ".join(f'"{k}"' for k in keywords)
                    frontmatter_lines.append(f"topic_keywords: [{kw_str}]")
            if self.topic_model_info:
                frontmatter_lines.append(f"topic_model: \"{self.topic_model_info['model_type']}\"")

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

        self.emit_event(EventNames.ZETTELKASTEN_CREATED, {
            "arxiv_id": self.arxiv_id,
            "kb_path": self.kb_path,
            "document_size": len(self.document),
        })

        print(f"Created zettelkasten note: {self.kb_path}")

        self.next(self.end)

    @traced_step
    # Metaflow @card stubs don't include `type` kwarg - see GitHub #15
    @card(type="blank")  # type: ignore[unknown-argument] - Metaflow stubs incomplete, type= is valid
    @step
    def end(self):
        """Emit final lineage and report results."""
        from gaius.hx.lineage.events import Dataset

        self.emit_event("paper.processing.completed", {
            "arxiv_id": self.arxiv_id,
            "kb_path": self.kb_path,
            "correlation_id": self.correlation_id,
        })

        # Collect outputs
        outputs = [Dataset.from_kb(self.kb_path)]
        if self.archive_path_result:
            outputs.append(Dataset.from_kb(self.archive_path_result))

        # Add topic model as output if trained
        if self.topic_model_info:
            outputs.append(Dataset(
                namespace="gaius.topics",
                name=f"{self.topic_model_info['model_type']}:{current.run_id}",
            ))

        # Add rubric reference if scoring was used
        if self.paper_score and self.rubric_version:
            outputs.append(Dataset(
                namespace="gaius.scoring",
                name=f"rubric:{self.scoring_rubric}:{self.rubric_version}",
            ))

        # Emit lineage COMPLETE
        self.emit_lineage_complete(outputs)

        # Build summary card
        current.card.append(Markdown("# ArxivDoclingFlow Summary"))
        current.card.append(Markdown(f"**arXiv ID:** [{self.arxiv_id}](https://arxiv.org/abs/{self.arxiv_id})"))
        current.card.append(Markdown(f"**Title:** {self.title}"))
        current.card.append(Markdown(f"**KB Note:** `{self.kb_path}`"))

        # Stats table
        stats = [
            ["Markdown Size", f"{len(self.markdown):,} chars"],
            ["PDF Size", f"{self.pdf_size:,} bytes"],
        ]
        if self.paper_score:
            stats.append(["Relevance Score", f"{self.paper_score.overall_score:.1%}"])
        if self.topic_model_info:
            stats.append(["Topics Discovered", str(self.topic_model_info['num_topics'])])
            stats.append(["Topic Model", self.topic_model_info['model_type'].upper()])
        current.card.append(Markdown("## Statistics"))
        current.card.append(Table(stats, headers=["Metric", "Value"]))

        # Lineage
        current.card.append(Markdown("## Lineage"))
        lineage_items = [f"- Input: `arXiv:{self.arxiv_id}`", f"- Output: `{self.kb_path}`"]
        if self.archive_path_result:
            lineage_items.append(f"- Archive: `{self.archive_path_result}`")
        if self.rubric_version:
            lineage_items.append(f"- Rubric: `{self.scoring_rubric}` v{self.rubric_version}")
        current.card.append(Markdown("\n".join(lineage_items)))

        # Console summary
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
        if self.paper_score:
            print(f"  Relevance:     {self.paper_score.overall_score:.1%}")
        if self.topic_model_info:
            print(f"  Topics:        {self.topic_model_info['num_topics']} ({self.topic_model_info['model_type']})")
        print("")
        print(f"  Lineage: arXiv:{self.arxiv_id} → {self.kb_path}")
        print("=" * 60)


if __name__ == "__main__":
    # Apply Metaflow config before running
    apply_metaflow_config("local")
    ArxivDoclingFlow()
