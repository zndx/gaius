"""ArticleCurationFlow - Metaflow pipeline for article research and publication.

This flow implements an 11-step pipeline that automates article curation:
1. start: Find unpublished articles in KB
2. grok_research_summary: Synthesize zettelkasten notes with Grok
3. select_article: Select article (optillm or explicit)
4. acquire_external: Fetch external sources (foreach parallel)
5. update_manifest: Write YAML manifest
6. create_draft: Generate draft with Grok, archive to hx/
7. create_base: BFO-grounded Base file with ref_start/ref_end
8. create_cards: Create collection cards from .base references (all pending)
9. enrich_cards: Generate summaries + render images (fail-fast per card)
10. publish_batch: Publish enriched cards, sync all KV stores
11. end: Emit lineage, report results

Enrichment before publish: Cards are enriched (summaries + images) BEFORE
being published to the site. Only fully enriched cards get published. Failed
cards stay 'pending' for the next run. This prevents cards with missing
content from appearing on gaius.zndx.org.

PRIVACY: This flow does NOT search the KB to avoid exposing private materials
in published articles. Only the article's own zk/ notes are used.

FAIL-FAST: This flow fails immediately if required services are unavailable.
No fallbacks or placeholder content is generated.

Usage:
    # Via Metaflow CLI
    python -m metaflow.cli run ArticleCurationFlow --article ai-reasoning-weekly

    # Via Gaius CLI
    uv run gaius-cli --cmd "/article curate ai-reasoning-weekly"
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import yaml
from metaflow import FlowSpec, Parameter, card, current, retry, step

from gaius.agents.metaagent.telemetry import TracedFlow, traced_step
from gaius.flows import register_flow
from gaius.flows.base import GaiusFlow
from gaius.flows.article_curation.common import (
    ArticleCandidate,
    ArticleReference,
    ArticleStatus,
    AcquiredSource,
    CardStatus,
    DraftHistoryEntry,
    find_extracted_path,
    get_kb_root,
    scan_articles,
)
from gaius.flows.card_upkeep.common import (
    extract_source_type,
    parse_base_file,
    traceable_id_to_url,
    update_base_file,
)
from gaius.flows.article_curation.progress import (
    emit_acquire,
    emit_base,
    emit_cards,
    emit_complete,
    emit_draft,
    emit_enrich,
    emit_failed,
    emit_publish,
    emit_research,
    emit_select,
    emit_start,
    emit_summarize,
    generate_run_id,
)
from gaius.core.budgets import EXTERNAL_MAX_TOKENS

logger = logging.getLogger(__name__)


@register_flow("article_curation")
class ArticleCurationFlow(TracedFlow, GaiusFlow):
    """Metaflow pipeline for article research and publication.

    Automates the research-to-publication workflow:
    - Synthesizes article's zk/ notes with Grok (large context window)
    - Selects article to advance (optillm or explicit --article parameter)
    - Acquires EXTERNAL sources only (arxiv required, others optional)
    - Generates draft with Grok, archives to hx/
    - Creates BFO-grounded Base file with character offsets

    PRIVACY: Does NOT search the broader KB to avoid exposing private
    materials in published articles.

    FAIL-FAST: Fails immediately if:
    - XAI_API_KEY not configured (Grok required)
    - No articles found with zk/ notes
    - arXiv fetcher fails (required source)

    OTel Integration:
        - Inherits from TracedFlow for automatic span creation
        - Emits semantic events for key operations
    """

    article_slug = Parameter(
        "article",
        help="Article slug to curate (if not provided, selects from pending)",
        default=None,
        required=False,
    )

    max_sources = Parameter(
        "max_sources",
        help="Maximum external sources to acquire per fetcher",
        default=10,
        type=int,
    )

    optillm_technique = Parameter(
        "optillm_technique",
        help="optillm technique for article selection (cot_reflection, bon, plansearch)",
        default="cot_reflection",
    )

    # NOTE: skip_optillm was removed - optillm is REQUIRED for article selection.
    # Use --article to specify a specific article directly if needed.

    skip_grok_sync = Parameter(
        "skip_grok_sync",
        help="Skip Grok Collections API sync",
        default=False,  # Fail-fast: require Grok Collections by default
        type=bool,
    )

    dry_run = Parameter(
        "dry_run",
        help="Dry run mode - don't write to KB",
        default=False,
        type=bool,
    )

    @traced_step
    @step
    def start(self):
        """Find unpublished articles in KB.

        Scans current/articles/*/ for articles with pending/researching
        status that have zettelkasten notes in zk/.
        """
        from gaius.hx.lineage.events import Dataset

        # Generate run_id for progress tracking (pg_notify)
        self.progress_run_id = generate_run_id()
        emit_start(self.progress_run_id, self.article_slug)

        # Use kb_root property from GaiusFlow (reads GAIUS_KB_ROOT env var)
        kb_root_path = self.kb_root

        # Emit lineage START
        self.emit_lineage_start(
            job_name="article_curation",
            inputs=[Dataset.from_source("kb", "articles")],
        )

        # Scan for candidates
        candidates = scan_articles(self.kb_root)

        if not candidates:
            error_msg = (
                "No unpublished articles found with zettelkasten notes.\n"
                "  Guru Meditation: #ACF.00000001.NOARTICLES\n"
                "  Create an article with: /article new {slug}"
            )
            emit_failed(self.progress_run_id, error_msg)
            raise RuntimeError(error_msg)

        # Fetch card stats from database for fairness-aware selection
        from gaius.flows.article_curation.common import fetch_article_card_stats
        try:
            card_stats = asyncio.get_event_loop().run_until_complete(
                fetch_article_card_stats([c.slug for c in candidates])
            )
        except RuntimeError:
            card_stats = asyncio.new_event_loop().run_until_complete(
                fetch_article_card_stats([c.slug for c in candidates])
            )

        # Populate card stats on candidates
        for c in candidates:
            stats = card_stats.get(c.slug, {})
            c.pending_cards = stats.get("pending_cards", 0)
            c.total_cards = stats.get("total_cards", 0)
            c.last_curated_at = stats.get("last_curated_at")

        print(f"Found {len(candidates)} candidate articles:")
        for c in candidates:
            print(f"  - {c.slug}: {c.title} (zk: {c.zk_count}, pending_cards: {c.pending_cards}, status: {c.status.value})")

        # If specific article requested, filter to it
        if self.article_slug:
            candidates = [c for c in candidates if c.slug == self.article_slug]
            if not candidates:
                error_msg = (
                    f"Article '{self.article_slug}' not found or not ready for curation.\n"
                    "  Guru Meditation: #ACF.00000001.NOARTICLES\n"
                    f"  Check current/articles/{self.article_slug}/ exists with zk/ notes"
                )
                emit_failed(self.progress_run_id, error_msg)
                raise RuntimeError(error_msg)

        self.candidates = candidates
        self.candidate_slugs = [c.slug for c in candidates]

        # Verify XAI is configured (required for Grok)
        from gaius.core.config import get_config

        xai_key = get_config().providers.xai.api_key
        if not xai_key:
            error_msg = (
                "XAI_API_KEY not configured - Grok is required for article curation.\n"
                "  Guru Meditation: #ACF.00000002.NOXAI\n"
                "  Set XAI_API_KEY environment variable"
            )
            emit_failed(self.progress_run_id, error_msg)
            raise RuntimeError(error_msg)

        self.emit_event("article_curation.candidates.found", {
            "count": len(candidates),
            "slugs": self.candidate_slugs,
        })

        # Skip KB research (privacy) - go directly to Grok summary
        self.next(self.grok_research_summary)

    @traced_step
    @card(type="blank")  # type: ignore[unknown-argument]
    @step
    def grok_research_summary(self):
        """Synthesize research with Grok into zettelkasten summary.

        Uses Grok (large context window) to create a research summary
        that informs article selection.
        """
        import asyncio

        # Count zk notes for progress reporting
        zk_count = sum(c.zk_count for c in self.candidates)
        emit_research(self.progress_run_id, zk_count)

        print("Generating research summary with Grok...")

        try:
            summary_result = asyncio.get_event_loop().run_until_complete(
                self._generate_grok_summary()
            )
        except RuntimeError:
            summary_result = asyncio.new_event_loop().run_until_complete(
                self._generate_grok_summary()
            )

        self.research_summary = summary_result
        print(f"Research summary generated: {len(summary_result)} chars")

        # Write to zk/ if not dry run
        if not self.dry_run and self.candidates:
            self._write_research_summary()

        self.next(self.select_article)

    async def _generate_grok_summary(self) -> str:
        """Generate research summary using Grok API.

        Reads the article's own zk/ notes (not broader KB) to avoid
        exposing private materials in published articles.

        Returns:
            Research summary text

        Raises:
            RuntimeError: If Grok is unavailable (fail-fast)
        """
        from gaius.engine.backends.external.xai_backend import XAIBackend

        backend = XAIBackend()

        if not backend.is_available:
            raise RuntimeError(
                "XAI backend not available - Grok is required.\n"
                "  Guru Meditation: #ACF.00000002.NOXAI\n"
                "  Set XAI_API_KEY environment variable"
            )

        # Build context from article's zk/ notes (NOT broader KB)
        context_parts = []
        for candidate in self.candidates:
            context_parts.append(f"## Article: {candidate.title}")
            context_parts.append(f"Status: {candidate.status.value}")
            context_parts.append(f"Slug: {candidate.slug}")
            context_parts.append("")

            # Read zk/ notes directly
            zk_dir = Path(candidate.kb_path) / "zk"
            if zk_dir.exists():
                context_parts.append("### Zettelkasten Notes:")
                for zk_file in sorted(zk_dir.glob("*.md"))[:10]:
                    content = zk_file.read_text()
                    context_parts.append(f"\n#### {zk_file.name}")
                    # Include first 1500 chars of each note
                    context_parts.append(content[:1500])
                    if len(content) > 1500:
                        context_parts.append("...")
                context_parts.append("")

            # Include research hints from frontmatter
            hints = candidate.research_hints
            if hints:
                context_parts.append("### Research Hints:")
                if kw := hints.get("keywords"):
                    context_parts.append(f"- Keywords: {', '.join(kw[:10])}")
                if cats := hints.get("arxiv_categories"):
                    context_parts.append(f"- arXiv categories: {', '.join(cats[:5])}")
                context_parts.append("")

        context = "\n".join(context_parts)

        system_prompt = """You are a senior research analyst creating a zettelkasten summary.

Your task is to synthesize the article's research notes into a coherent summary that:
1. Identifies key themes and connections
2. Highlights the most promising directions
3. Notes gaps requiring additional external research
4. Provides actionable guidance for article development

Output as markdown with YAML frontmatter including type, created_at, and summary_of fields."""

        user_prompt = f"""Synthesize the following article research into a zettelkasten summary:

{context}

Create a comprehensive research summary that will guide article development."""

        response = await backend.complete(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            model="grok-4-1-fast",
            temperature=0.3,
            max_tokens=EXTERNAL_MAX_TOKENS,
        )

        if not response.success:
            raise RuntimeError(
                f"Grok summary generation failed: {response.error}\n"
                "  Guru Meditation: #ACF.00000003.GROKFAIL\n"
                "  Check XAI API status and quota"
            )

        return response.content

    def _write_research_summary(self):
        """Write research summary to zk/ directory."""
        if not self.candidates:
            return

        candidate = self.candidates[0]
        zk_dir = Path(candidate.kb_path) / "zk"
        zk_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%H%M%S")
        filename = f"{timestamp}_research_summary.md"
        filepath = zk_dir / filename

        filepath.write_text(self.research_summary)
        print(f"Wrote research summary to: {filepath}")

    @traced_step
    @card(type="blank")  # type: ignore[unknown-argument]
    @step
    def select_article(self):
        """Select article to advance.

        If --article parameter provided, uses that directly.
        Otherwise uses optillm with cot_reflection technique (Atropos-RL traces).

        FAIL-FAST: optillm is REQUIRED for multi-candidate selection.
        """
        import asyncio

        # If specific article requested via --article, use it directly
        if self.article_slug and len(self.candidates) == 1:
            self.selected_candidate = self.candidates[0]
            self.selected_slug = self.selected_candidate.slug
            self.selection_confidence = 1.0
            self.selection_trace = {
                "selected_slug": self.selected_slug,
                "confidence": 1.0,
                "reasoning": "Explicitly specified via --article parameter",
            }
            print(f"Using specified article: {self.selected_candidate.title}")

        # Use optillm for selection (REQUIRED - no fallback)
        else:
            print(f"Selecting article using optillm ({self.optillm_technique})...")

            try:
                selection = asyncio.get_event_loop().run_until_complete(
                    self._select_with_optillm()
                )
            except RuntimeError as e:
                if "no running event loop" in str(e).lower():
                    selection = asyncio.new_event_loop().run_until_complete(
                        self._select_with_optillm()
                    )
                else:
                    raise

            self.selected_slug = selection["selected_slug"]
            self.selection_trace = selection
            self.selection_confidence = selection.get("confidence", 0.0)

            # Find selected candidate
            self.selected_candidate = next(
                (c for c in self.candidates if c.slug == self.selected_slug),
                None,
            )

            if not self.selected_candidate:
                raise RuntimeError(
                    f"optillm selected unknown article '{self.selected_slug}'.\n"
                    "  Guru Meditation: #ACF.00000004.SELECTFAIL\n"
                    f"  Available: {[c.slug for c in self.candidates]}"
                )

            print(f"Selected article: {self.selected_candidate.title}")
            print(f"Confidence: {self.selection_confidence:.2f}")

            # Retain the reasoning — a primary deliverable — as the HX data product
            # hx.cot_reasoning (Signals Polaris/Iceberg on RustFS) with this run's
            # flow/step/subject context, so the corpus accumulates with history and
            # any signals-protocol federated engine can surface it. FAIL-FAST: a lost
            # trace is a failed run (the selection is the crucible, the trace the ore).
            self.cot_record = self._retain_cot_reasoning(selection)

        self.emit_event("article_curation.article.selected", {
            "slug": self.selected_slug,
            "confidence": self.selection_confidence,
            "technique": self.optillm_technique if len(self.candidates) > 1 else "explicit",
            "cot_record_id": (getattr(self, "cot_record", None) or {}).get("id", ""),
        })

        # Emit progress: article selected
        emit_select(
            self.progress_run_id,
            self.selected_slug,
            self.selected_candidate.title if self.selected_candidate else self.selected_slug,
        )

        # Ensure article is registered in database with 1:1 collection
        if not self.dry_run and self.selected_candidate:
            try:
                article_id, collection_id = asyncio.get_event_loop().run_until_complete(
                    self._ensure_article_in_db()
                )
            except RuntimeError:
                article_id, collection_id = asyncio.new_event_loop().run_until_complete(
                    self._ensure_article_in_db()
                )
            self.article_id = article_id
            self.collection_id = collection_id
            print(f"Registered article in DB: {article_id} with collection {collection_id}")
        else:
            self.article_id = None
            self.collection_id = None

        # Define source types for parallel fetching
        # All sources are fetched in parallel
        # Required: arxiv (academic preprints), brave (open web research)
        # Optional: biorxiv (life sciences - may not be relevant for all topics)
        self.source_types = ["arxiv", "biorxiv", "brave"]

        self.next(self.acquire_external)

    def _retain_cot_reasoning(self, selection: dict) -> dict:
        """Land the select_article reasoning trace in HX; return the CotRecord as a dict."""
        import json as _json
        import os as _os
        from dataclasses import asdict

        from gaius.engine.sentinel_claim import EXTRACT
        from gaius.hx.cot_reasoning import store_cot_reasoning

        flow_name, run_id, pathspec = type(self).__name__, "", ""
        try:
            from metaflow import current

            flow_name = str(getattr(current, "flow_name", "") or flow_name)
            run_id = str(getattr(current, "run_id", "") or "")
            pathspec = str(getattr(current, "pathspec", "") or "")
        except Exception:
            pass
        decision_only = {
            k: v for k, v in selection.items()
            if k not in ("raw_response", "reasoning_trace", "reasoning_layers", "prompt")
        }
        rec = store_cot_reasoning(
            flow_name=flow_name,
            step_name="select_article",
            run_id=run_id or "unknown",
            pathspec=pathspec,
            subject=str(selection.get("selected_slug") or ""),
            technique=str(selection.get("technique") or self.optillm_technique),
            model_name=str(selection.get("model") or "thinking"),
            prompt=str(selection.get("prompt") or ""),
            reasoning_trace=str(selection.get("reasoning_trace") or ""),
            raw_response=str(selection.get("raw_response") or ""),
            reasoning_layers=str(selection.get("reasoning_layers") or ""),
            output=_json.dumps(decision_only, default=str),
            decision=str(selection.get("selected_slug") or ""),
            confidence=float(selection.get("confidence") or 0.0),
            input_tokens=int(selection.get("input_tokens") or 0) or None,
            output_tokens=int(selection.get("output_tokens") or 0) or None,
            latency_ms=int(selection.get("latency_ms") or 0) or None,
            yk_app_id=_os.environ.get("GAIUS_YK_APPLICATION_ID", ""),
            yk_queue=EXTRACT.queue,
        )
        print(
            f"Retained reasoning in HX {rec.table_identifier}: id={rec.id} "
            f"snapshot={rec.snapshot_id} ({selection.get('output_tokens') or '?'} tokens)"
        )
        return asdict(rec)

    async def _select_with_optillm(self) -> dict[str, Any]:
        """Select article using engine's capability-based scheduling.

        Routes through the Gaius Engine's gRPC scheduler which handles:
        - Agent configuration lookup (leader agent has optillm backend)
        - optillm technique selection (cot_reflection for leader)
        - Metrics collection via OTel
        - Resource management

        Returns:
            Selection result with selected_slug, confidence, and trace

        Raises:
            RuntimeError: If engine is unavailable or selection fails (fail-fast)
        """
        from gaius.client.engine_client import get_engine_client

        # Build candidate descriptions with card stats for fair selection
        candidates_text = []
        for i, c in enumerate(self.candidates, 1):
            last_curated = "never"
            if c.last_curated_at:
                days_ago = (datetime.now(c.last_curated_at.tzinfo) - c.last_curated_at).days
                last_curated = f"{days_ago} days ago" if days_ago > 0 else "today"

            has_keywords = bool(c.research_hints.get("keywords"))
            has_queries = bool(c.research_hints.get("news_queries"))
            readiness = "ready" if (has_keywords or has_queries) else "NOT READY (missing keywords/news_queries)"

            candidates_text.append(
                f"### Candidate {i}: {c.title}\n"
                f"- Slug: {c.slug}\n"
                f"- Status: {c.status.value}\n"
                f"- Zettelkasten notes: {c.zk_count}\n"
                f"- Pending cards in queue: {c.pending_cards}\n"
                f"- Total cards created: {c.total_cards}\n"
                f"- Last curated: {last_curated}\n"
                f"- Curation readiness: {readiness}\n"
            )

        prompt = f"""Select the best article to advance for publication.

## Candidates

{chr(10).join(candidates_text)}

## Research Summary

{self.research_summary[:2000]}

## Selection Criteria (weighted equally):
1. **Curation Readiness** - NEVER select articles marked "NOT READY". They lack the metadata needed for source fetching and will fail.
2. **Collection Balance** - STRONGLY prefer articles with FEWER pending cards to maintain diverse content on the landing page. Articles with large backlogs should be deprioritized.
3. **Recency Fairness** - Prefer articles that haven't been curated recently (round-robin across all articles).
4. Timeliness - How recent are the sources?
5. Novelty - Does it offer fresh insights?
6. Audience Fit - Will ML practitioners care?
7. Source Quality - Authoritative citations?

IMPORTANT: If one article has significantly more pending cards than others, you MUST select a different article to maintain collection diversity. A balanced landing page with varied topics is more valuable than deep coverage of one topic.

Respond with JSON:
{{
  "selected_slug": "<slug of selected article>",
  "confidence": <0.0-1.0>,
  "reasoning": "<explain how balance and fairness influenced your choice>",
  "criteria_scores": {{
    "collection_balance": {{"<slug>": <score>, ...}},
    "recency_fairness": {{"<slug>": <score>, ...}},
    "timeliness": {{"<slug>": <score>, ...}},
    ...
  }}
}}"""

        # Use engine's capability-based scheduling:
        # - "leader" agent routes through optillm with cot_reflection technique
        # - Provides better article selection via chain-of-thought reasoning
        #
        # Retry on a transient engine/vLLM blip: optillm binds thinking as its vLLM,
        # and thinking can restart mid-request under GPU churn (reported as
        # #OPT.00000011.VLLMRESTART / #OPT.00000004.NOVLLM). The workload watchdog +
        # the engine's auto-restart bring thinking back, so a backoff + retry
        # usually succeeds. cot_reflection is expensive, so cap the attempts.
        import asyncio as _asyncio

        response = None
        last_err = "unknown"
        attempts = 3
        for attempt in range(1, attempts + 1):
            try:
                # Dual-constraint Complete over the signals-protocol: the
                # method (cot_reasoning → cot_reflection) + model (thinking)
                # pair is fulfilled ENGINE-NATIVELY, so BOTH reasoning layers
                # come back — the model's native trace AND the scaffold.
                from gaius.flows.lattice import complete as lattice_complete

                response = await _asyncio.to_thread(
                    lattice_complete,
                    prompt,
                    capabilities=["cot_reasoning", "thinking"],
                    system_prompt="You are an editorial curator selecting articles for publication.",
                    temperature=0.7,  # Higher for exploration
                    # Deep reasoning IS the product: Qwen3.8's native <think> block on
                    # this ranking prompt routinely runs 10-15k tokens BEFORE the
                    # cot_reflection <thinking>/<output> answer. A 4096 cap cut the
                    # generation inside the think block (finish_reason=length), vLLM
                    # returned content=None, and optillm's regex died with HTTP 500
                    # "expected string or bytes-like object, got 'NoneType'" — a
                    # deterministic failure, not a transient. 262k context: give it room.
                    max_tokens=32768,
                    timeout_s=900.0,
                )
                if response.text:
                    break
                last_err = "empty response (#ACF.00000022.EMPTYRESPONSE)"
            except Exception as e:  # noqa: BLE001 — transient engine/vLLM failures
                last_err = str(e)
            if attempt < attempts:
                print(
                    f"[select_article] attempt {attempt}/{attempts} failed: {last_err}; "
                    f"waiting 60s for thinking to recover, then retrying",
                    flush=True,
                )
                await _asyncio.sleep(60)
        else:
            raise RuntimeError(
                f"Article selection failed after {attempts} attempts: {last_err}\n"
                "  Guru Meditation: #ACF.00000005.ENGINEFAIL\n"
                "  Ensure engine + thinking are healthy: /health fix engine\n"
                "  Or specify single article with --article to bypass selection"
            )

        # Parse the SELECTION JSON. cot_reflection is deep by design — its long
        # reasoning trace (a primary deliverable, accumulated to HX/Iceberg) itself
        # contains JSON-like structures (criteria_scores, nested braces, worked
        # examples), so a naive first-{ to last-} grab captures an invalid span and
        # fails #ACF.00000006.BADJSON even when the selection is correct. Instead
        # scan for every balanced JSON object and take the LAST one carrying
        # "selected_slug" — robust to arbitrarily rich reasoning ahead of the answer.
        content = response.text
        decoder = json.JSONDecoder()
        selection = None
        scan = 0
        while True:
            brace = content.find("{", scan)
            if brace < 0:
                break
            try:
                obj, obj_end = decoder.raw_decode(content, brace)
                scan = obj_end
                if isinstance(obj, dict) and "selected_slug" in obj:
                    selection = obj  # keep the last valid selection object
            except json.JSONDecodeError:
                scan = brace + 1

        if selection is not None:
            # Preserve the full reasoning trace — it is the deliverable, not scaffolding.
            selection["raw_response"] = content
            # The trace, richest first: the dual-constraint reasoning layers
            # (model-native trace + method scaffold, tagged), else the
            # separated reasoning_content, else the scaffold regex fallback.
            layers = [
                dict(layer)
                for layer in (getattr(response, "reasoning", ()) or ())
                if layer.get("text")
            ]
            trace = "\n\n".join(
                f"[{layer.get('layer', '?')}:{layer.get('producer', '')}]\n{layer['text']}"
                for layer in layers
            )
            if not trace:
                trace = getattr(response, "reasoning_content", "") or ""
            if not trace:
                import re as _re

                parts = _re.findall(
                    r"<(thinking|reflection)>(.*?)</\1>", content, flags=_re.DOTALL
                )
                trace = "\n\n".join(f"<{tag}>{body.strip()}</{tag}>" for tag, body in parts)
            selection["reasoning_trace"] = trace
            selection["reasoning_layers"] = json.dumps(layers) if layers else ""
            fulfilled = getattr(response, "fulfilled_by", "") or ""
            selection["fulfilled_by"] = fulfilled
            selection["technique"] = (
                fulfilled.split("@", 1)[0] if fulfilled else self.optillm_technique
            )
            selection["latency_ms"] = getattr(response, "latency_ms", 0)
            # Context the HX product (hx.cot_reasoning) retains with the trace.
            selection["model"] = str(getattr(response, "model", "") or "thinking")
            selection["prompt"] = prompt
            selection["input_tokens"] = int(
                getattr(response, "prompt_tokens", None) or getattr(response, "input_tokens", 0) or 0
            )
            selection["output_tokens"] = int(
                getattr(response, "completion_tokens", None) or getattr(response, "output_tokens", 0) or 0
            )
            return selection

        # No parseable selection object anywhere in the response — a real error.
        raise RuntimeError(
            "optillm returned no parseable selection JSON.\n"
            "  Guru Meditation: #ACF.00000006.BADJSON\n"
            f"  Response tail: ...{content[-300:]}"
        )

    async def _ensure_article_in_db(self) -> tuple[str, str]:
        """Ensure article exists in Postgres with matching 1:1 collection.

        Creates both article and collection atomically using same slug.
        If article already exists, returns existing IDs.

        Returns:
            Tuple of (article_id, collection_id)

        Raises:
            RuntimeError: If database operation fails (fail-fast)
        """
        import asyncpg

        from gaius.engine.services.collection_service import CollectionService

        if not self.selected_candidate:
            raise RuntimeError(
                "No selected candidate for DB registration.\n"
                "  Guru Meditation: #ACF.00000004.SELECTFAIL"
            )

        from gaius.core.config import get_database_url
        db_url = get_database_url()

        async with asyncpg.create_pool(db_url, min_size=1, max_size=3) as pool:
            service = CollectionService(pool)

            # Check if article already exists
            existing = await service.get_article_by_slug(self.selected_candidate.slug)
            if existing:
                logger.info(
                    f"Article already in DB: {existing.article_id} "
                    f"(collection: {existing.collection_id})"
                )
                return existing.article_id, existing.collection_id or ""

            # Create article with 1:1 collection
            try:
                article, collection = await service.create_article_with_collection(
                    slug=self.selected_candidate.slug,
                    title=self.selected_candidate.title,
                    kb_path=self.selected_candidate.kb_path,
                    arxiv_categories=self.selected_candidate.research_hints.get("arxiv_categories"),
                    keywords=self.selected_candidate.research_hints.get("keywords"),
                )

                logger.info(
                    f"Created article {article.article_id} "
                    f"with collection {collection.collection_id}"
                )
                return article.article_id, collection.collection_id

            except Exception as e:
                raise RuntimeError(
                    f"Failed to create article in database: {e}\n"
                    "  Guru Meditation: #ACF.00000012.DBFAIL\n"
                    "  Check database connectivity and schema migration"
                ) from e

    @traced_step
    @step
    def acquire_external(self):
        """Fan out to parallel external source fetchers.

        Fetches from arxiv, biorxiv, brave, philpapers, philevents.
        EXTERNAL sources only - avoids duplicating KB content.
        """
        print(f"Starting external source acquisition for: {self.selected_slug}")
        self.next(self.run_fetcher, foreach="source_types")

    @traced_step
    @step
    def run_fetcher(self):
        """Execute single fetcher (parallel branch)."""
        import asyncio

        source_type = self.input  # type: ignore[attr-defined] - metaflow FlowSpec, lacks stubs
        print(f"Fetching {source_type} sources...")

        try:
            results = asyncio.get_event_loop().run_until_complete(
                self._fetch_sources(source_type)
            )
        except RuntimeError:
            results = asyncio.new_event_loop().run_until_complete(
                self._fetch_sources(source_type)
            )

        self.fetcher_results = results
        self.source_type_branch = source_type
        print(f"Fetched {len(results)} {source_type} sources")

        self.next(self.join_fetchers)

    async def _fetch_sources(self, source_type: str) -> list[AcquiredSource]:
        """Fetch sources from a specific fetcher.

        Args:
            source_type: Fetcher type (arxiv, biorxiv, brave)

        Returns:
            List of AcquiredSource objects

        Raises:
            RuntimeError: If required fetcher (arXiv) fails (fail-fast)
        """
        if not self.selected_candidate:
            raise RuntimeError(
                "No selected candidate for source fetching.\n"
                "  Guru Meditation: #ACF.00000004.SELECTFAIL"
            )

        query = self.selected_candidate.title
        hints = self.selected_candidate.research_hints

        if source_type == "arxiv":
            return await self._fetch_arxiv(query, hints)
        elif source_type == "biorxiv":
            return await self._fetch_biorxiv(query, hints)
        elif source_type == "brave":
            return await self._fetch_brave(query, hints)
        else:
            raise RuntimeError(
                f"Unknown source type: {source_type}.\n"
                "  Guru Meditation: #ACF.00000010.BADSOURCE\n"
                "  Supported: arxiv, biorxiv, brave"
            )

    async def _fetch_arxiv(self, query: str, hints: dict) -> list[AcquiredSource]:
        """Fetch from arXiv API.

        Args:
            query: Search query (article title)
            hints: Research hints including arxiv_categories

        Returns:
            List of AcquiredSource objects

        Raises:
            RuntimeError: If arXiv API fails or returns no results (fail-fast)
        """
        import httpx
        import feedparser
        import re
        from urllib.parse import urlencode

        categories = hints.get("arxiv_categories")
        if not categories:
            raise RuntimeError(
                "Article missing arxiv_categories in frontmatter.\n"
                "  Guru Meditation: #ACF.00000013.NOHINTS\n"
                "  Add arxiv_categories: [cs.AI, cs.LG, ...] to article.md frontmatter"
            )
        keywords = hints.get("keywords")
        if not keywords:
            raise RuntimeError(
                "Article missing keywords in frontmatter.\n"
                "  Guru Meditation: #ACF.00000013.NOHINTS\n"
                "  Add keywords: [keyword1, keyword2, ...] to article.md frontmatter"
            )

        # Build arXiv query from keywords or title words
        # arXiv API has issues with multi-word terms, so we split them
        all_terms: list[str] = []
        if keywords:
            # Split multi-word keywords into individual words
            for kw in keywords[:5]:
                all_terms.extend(kw.split())
        else:
            # Extract words from title (remove special chars)
            title_words = re.sub(r"[^a-zA-Z\s]", " ", query).split()
            all_terms = title_words

        # Filter to valid search terms (single words, 4+ chars, not stop words)
        # Allow alphanumeric and hyphens (e.g., "multi-agent")
        stop_words = {"the", "a", "an", "and", "or", "for", "to", "in", "of", "with", "from"}
        search_terms = [
            w for w in all_terms
            if len(w) >= 4 and w.lower() not in stop_words and re.match(r"^[\w-]+$", w)
        ][:8]

        # Deduplicate while preserving order
        seen = set()
        unique_terms = []
        for term in search_terms:
            if term.lower() not in seen:
                seen.add(term.lower())
                unique_terms.append(term)

        # Build category filter
        cat_query = " OR ".join([f"cat:{c}" for c in categories[:3]])

        # Build search query using OR for broader recall
        # (AND would be too restrictive for rare topic combinations)
        term_query = " OR ".join([f"all:{term}" for term in unique_terms])
        search_query = f"({term_query}) AND ({cat_query})"

        params = {
            "search_query": search_query,
            "start": 0,
            "max_results": self.max_sources,
            "sortBy": "submittedDate",
            "sortOrder": "descending",
        }

        url = f"https://export.arxiv.org/api/query?{urlencode(params)}"
        logger.debug(f"arXiv query: {search_query}")

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(url)

                if response.status_code != 200:
                    raise RuntimeError(
                        f"arXiv API returned status {response.status_code}.\n"
                        "  Guru Meditation: #ACF.00000007.NOSOURCES\n"
                        "  Check network connectivity and arXiv API status"
                    )

                feed = feedparser.parse(response.text)
                sources = []

                for entry in feed.entries:
                    sources.append(AcquiredSource.from_fetcher_result(
                        source_type="arxiv",
                        url=entry.get("link", ""),
                        title=entry.get("title", "").replace("\n", " ").strip(),
                        summary=entry.get("summary", "").strip()[:500],
                        metadata={
                            "authors": [a.get("name", "") for a in entry.get("authors", [])],
                            "categories": [t.get("term", "") for t in entry.get("tags", [])],
                            # Publication date rides to the source file and on to
                            # the card's source_date — the content_currency intent
                            # objective was blind to curated cards without it
                            # (2026-09-03: 374 cards, every curation batch, NULL).
                            "published": entry.get("published", ""),
                            "updated": entry.get("updated", ""),
                        },
                    ))

                return sources[:int(self.max_sources)]

        except httpx.RequestError as e:
            raise RuntimeError(
                f"arXiv API request failed: {e}\n"
                "  Guru Meditation: #ACF.00000007.NOSOURCES\n"
                "  Check network connectivity"
            ) from e

    async def _fetch_biorxiv(self, query: str, hints: dict) -> list[AcquiredSource]:
        """Fetch from bioRxiv/medRxiv API.

        bioRxiv is OPTIONAL - returns empty list on failure instead of raising.

        Args:
            query: Search query (article title)
            hints: Research hints including keywords

        Returns:
            List of AcquiredSource objects (empty on failure)
        """
        import httpx
        import re

        keywords = hints.get("keywords", [])

        # Build search query from keywords
        search_terms = []
        for kw in keywords[:5]:
            # bioRxiv search works with simple terms
            clean_term = re.sub(r"[^a-zA-Z0-9\s-]", "", kw).strip()
            if clean_term:
                search_terms.append(clean_term)

        if not search_terms:
            # Fall back to title words
            title_words = re.sub(r"[^a-zA-Z\s]", " ", query).split()
            search_terms = [w for w in title_words if len(w) >= 4][:5]

        if not search_terms:
            logger.warning("No valid search terms for bioRxiv (optional source)")
            return []

        # bioRxiv API endpoint (searches both bioRxiv and medRxiv)
        # API docs: https://api.biorxiv.org/
        search_query = "+".join(search_terms[:3])
        url = f"https://api.biorxiv.org/details/biorxiv/{search_query}/0/{self.max_sources}"

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(url)

                if response.status_code != 200:
                    logger.warning(f"bioRxiv API returned status {response.status_code} (optional source)")
                    return []

                data = response.json()
                collection = data.get("collection", [])
                sources = []

                for entry in collection:
                    doi = entry.get("doi", "")
                    sources.append(AcquiredSource.from_fetcher_result(
                        source_type="biorxiv",
                        url=f"https://doi.org/{doi}" if doi else entry.get("url", ""),
                        title=entry.get("title", "").strip(),
                        summary=entry.get("abstract", "")[:500],
                        metadata={
                            "authors": entry.get("authors", ""),
                            "category": entry.get("category", ""),
                            "doi": doi,
                            "server": entry.get("server", "biorxiv"),
                        },
                    ))

                return sources[:int(self.max_sources)]

        except httpx.RequestError as e:
            logger.warning(f"bioRxiv API request failed (optional source): {e}")
            return []

    async def _fetch_brave(self, query: str, hints: dict) -> list[AcquiredSource]:
        """Fetch from Brave Search API for open web research.

        Brave is REQUIRED - open web research is a first-class source that
        discovers content beyond academic preprint servers. Searches for
        authoritative research content across the web.

        Exchange Capture: Brave explicitly allows API responses to be used for
        LLM model ops (tuning, RL, continual learning). All exchanges are
        captured to Iceberg via gaius.hx.exchange for training data collection.

        Args:
            query: Search query (article title)
            hints: Research hints including keywords and news_queries

        Returns:
            List of AcquiredSource objects

        Raises:
            RuntimeError: If Brave API fails or BRAVE_API_KEY not set (fail-fast)
        """
        import httpx
        import time

        from gaius.hx import ExchangeRecord, get_exchange_capture

        from gaius.core.config import get_config as _get_config

        api_key = _get_config().providers.brave.api_key
        if not api_key:
            raise RuntimeError(
                "BRAVE_API_KEY not configured - REQUIRED for open web research.\n"
                "  Guru Meditation: #ACF.00000015.NOBRAVE\n"
                "  Set BRAVE_API_KEY environment variable"
            )

        keywords = hints.get("keywords", [])
        news_queries = hints.get("news_queries", [])

        # Build search query combining keywords and news queries
        search_terms = []
        if news_queries:
            search_terms.extend(news_queries[:2])
        if keywords:
            search_terms.extend(keywords[:3])

        if not search_terms:
            raise RuntimeError(
                "No search terms for Brave - article missing keywords/news_queries.\n"
                "  Guru Meditation: #ACF.00000013.NOHINTS\n"
                "  Add keywords and/or news_queries to article.md frontmatter"
            )

        # Add "research" or "paper" to bias toward academic content
        search_query = " ".join(search_terms) + " research paper"

        url = "https://api.search.brave.com/res/v1/web/search"
        headers = {
            "Accept": "application/json",
            "X-Subscription-Token": api_key,
        }
        # Currency IS the intent (content_currency: source within current_days,
        # 7 d). Search the past week first and widen to the past month only to
        # fill the count, freshest first. `freshness=py` made the web half of
        # every curate year-old by construction — 68 such cards were archived
        # off the public surface on 2026-09-05 after four days of band FAILs.
        freshness_ladder = ("pw", "pm")
        max_n = int(self.max_sources)
        skip_domains = ["twitter.com", "facebook.com", "reddit.com", "linkedin.com"]

        # Source integrity (2026-09-06): week-first freshness surfaced ten vendor
        # listicles in one curate and the pipeline published them as research.
        # Two lines of defence at acquisition, both explainable:
        #  1. a Brave Goggle (config/brave/web-half.goggle) re-ranks the index —
        #     marketing URL shapes and known vendors discarded, primary sources
        #     boosted — passed inline; missing goggle = fail-fast, never an
        #     unfiltered search;
        #  2. looks_like_marketing() on every result that still comes back —
        #     rejections are kept in the exchange record, so what was refused is
        #     as auditable as what was admitted.
        from pathlib import Path as _Path

        from gaius.flows.article_curation.common import looks_like_marketing

        goggle_path = _Path(__file__).resolve().parents[4] / "config" / "brave" / "web-half.goggle"
        if not goggle_path.is_file():
            raise RuntimeError(
                f"Brave goggle missing: {goggle_path}\n"
                "  Guru Meditation: #ACF.00000021.NOGOGGLE\n"
                "  The web half never runs unfiltered — restore config/brave/web-half.goggle"
            )
        goggle = goggle_path.read_text(encoding="utf-8")
        rejected: list[dict[str, str]] = []

        start_time = time.monotonic()

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                dated: list[tuple[str, AcquiredSource]] = []
                seen_urls: set[str] = set()
                used_freshness: list[str] = []
                for freshness in freshness_ladder:
                    if len(dated) >= max_n:
                        break
                    params = {
                        "q": search_query,
                        "count": max_n,
                        "safesearch": "moderate",
                        "freshness": freshness,
                        "goggles": goggle,
                    }
                    response = await client.get(url, headers=headers, params=params)

                    if response.status_code == 401:
                        raise RuntimeError(
                            "Brave API authentication failed.\n"
                            "  Guru Meditation: #ACF.00000015.NOBRAVE\n"
                            "  Check BRAVE_API_KEY is valid"
                        )

                    if response.status_code != 200:
                        raise RuntimeError(
                            f"Brave API returned status {response.status_code}.\n"
                            "  Guru Meditation: #ACF.00000015.NOBRAVE\n"
                            "  Check network connectivity and Brave API status"
                        )

                    used_freshness.append(freshness)
                    for entry in response.json().get("web", {}).get("results", []):
                        url_str = entry.get("url", "")
                        # Filter for likely academic/research sources
                        # Skip social media, news aggregators, etc.
                        if any(domain in url_str.lower() for domain in skip_domains):
                            continue
                        if url_str in seen_urls:
                            continue
                        seen_urls.add(url_str)
                        why = looks_like_marketing(url_str, entry.get("title", ""))
                        if why:
                            rejected.append({"url": url_str, "reason": why, "freshness": freshness})
                            continue
                        dated.append((str(entry.get("page_age") or ""), AcquiredSource.from_fetcher_result(
                            source_type="web",  # Use 'web' as source_type per schema
                            url=url_str,
                            title=entry.get("title", "").strip(),
                            summary=entry.get("description", "")[:500],
                            metadata={
                                "age": entry.get("age", ""),
                                # ISO page date when Brave has one — the precise
                                # source_date signal; `age` is the coarse fallback.
                                "page_age": entry.get("page_age", ""),
                                "language": entry.get("language", "en"),
                                "family_friendly": entry.get("family_friendly", True),
                                "freshness": freshness,
                            },
                        )))

                latency_ms = int((time.monotonic() - start_time) * 1000)
                # Freshest first (ISO page_age sorts lexically; undated last).
                dated.sort(key=lambda t: t[0], reverse=True)
                sources = [s for _, s in dated]
                if rejected:
                    logger.info(
                        "Brave web half: rejected %d marketing/aggregation result(s): %s",
                        len(rejected),
                        "; ".join(f"{r['url'][:60]} ({r['reason']})" for r in rejected[:5]),
                    )

                # Capture exchange to Iceberg for ML training (REQUIRED)
                # Brave explicitly allows API responses for model tuning/RL
                # Content is king - exchange data is critical training material
                if sources:
                    capture = get_exchange_capture()
                    record = ExchangeRecord(
                        provider="brave",
                        request_messages=[{"role": "user", "content": search_query}],
                        request_model="brave-search-v1",
                        request_params={
                            "count": max_n,
                            "freshness": used_freshness,
                            "goggle": "config/brave/web-half.goggle",
                            "rejected": rejected,
                        },
                        response_content=json.dumps([{
                            "url": s.url,
                            "title": s.title,
                            "summary": s.summary,
                        } for s in sources]),
                        latency_ms=latency_ms,
                        source_context={
                            "agent_alias": "article_curation_flow",
                            "task_type": "web_research",
                            "article_slug": self.selected_candidate.slug if self.selected_candidate else None,
                        },
                    )
                    result = await capture.capture(record)
                    if not result.success:
                        raise RuntimeError(
                            f"Brave exchange capture failed: {result.errors}\n"
                            "  Guru Meditation: #ACF.00000016.HXCAPTURE\n"
                            "  Check Iceberg/RustFS connectivity: /health fix hx"
                        )
                    logger.info(f"Captured Brave exchange: {len(sources)} results, {latency_ms}ms")

                return sources[:int(self.max_sources)]

        except httpx.RequestError as e:
            raise RuntimeError(
                f"Brave API request failed: {e}\n"
                "  Guru Meditation: #ACF.00000015.NOBRAVE\n"
                "  Check network connectivity"
            ) from e

    @traced_step
    @step
    def join_fetchers(self, inputs):
        """Merge parallel fetcher results.

        Fails if no arXiv sources acquired (arXiv is required).
        bioRxiv and Brave are optional - logged but don't block.
        """
        self.merge_artifacts(inputs, exclude=["fetcher_results", "source_type_branch"])  # type: ignore[attr-defined] - metaflow FlowSpec, lacks stubs

        # Collect all sources by type
        self.acquired_sources: list[AcquiredSource] = []
        sources_by_type: dict[str, int] = {}

        for inp in inputs:
            source_type = inp.source_type_branch
            count = len(inp.fetcher_results)
            sources_by_type[source_type] = count
            self.acquired_sources.extend(inp.fetcher_results)
            print(f"  {source_type}: {count} sources")

        print(f"Total sources acquired: {len(self.acquired_sources)}")

        # Emit progress: sources acquired
        emit_acquire(self.progress_run_id, len(self.acquired_sources))

        # Check required sources
        arxiv_count = sources_by_type.get("arxiv", 0)
        brave_count = sources_by_type.get("brave", 0)

        if arxiv_count == 0:
            raise RuntimeError(
                "No sources acquired from arXiv (required).\n"
                "  Guru Meditation: #ACF.00000007.NOSOURCES\n"
                "  Check network connectivity and arXiv API availability"
            )

        if brave_count == 0:
            raise RuntimeError(
                "No sources acquired from Brave (required).\n"
                "  Guru Meditation: #ACF.00000015.NOBRAVE\n"
                "  Check BRAVE_API_KEY and network connectivity"
            )

        # Log optional source status (don't fail)
        if sources_by_type.get("biorxiv", 0) == 0:
            logger.info("No bioRxiv sources acquired (optional - may not be relevant for topic)")

        self.emit_event("article_curation.sources.acquired", {
            "count": len(self.acquired_sources),
            "by_type": {
                st: len([s for s in self.acquired_sources if s.source_type == st])
                for st in self.source_types
            },
        })

        self.next(self.update_manifest)

    @traced_step
    @step
    def update_manifest(self):
        """Write YAML manifest with acquired sources."""
        print("Updating collection manifest...")

        if not self.selected_candidate:
            self.manifest_path = None
            self.next(self.sync_grok_collection)
            return

        manifest = {
            "version": "1.0",
            "article_slug": self.selected_candidate.slug,
            "article_title": self.selected_candidate.title,
            "created_at": datetime.now().isoformat(),
            "sources": [
                {
                    "source_id": s.source_id,
                    "source_type": s.source_type,
                    "url": s.url,
                    "title": s.title,
                    "acquired_at": s.fetched_at.isoformat() if s.fetched_at else None,
                }
                for s in self.acquired_sources
            ],
            "grok_collection_id": None,
        }

        if not self.dry_run:
            manifest_path = Path(self.selected_candidate.kb_path) / "manifest.yaml"
            manifest_path.write_text(yaml.dump(manifest, default_flow_style=False))
            self.manifest_path = str(manifest_path)
            print(f"Wrote manifest to: {manifest_path}")

            # Also write source files
            sources_dir = Path(self.selected_candidate.kb_path) / "sources"
            sources_dir.mkdir(parents=True, exist_ok=True)
            for source in self.acquired_sources:
                source_file = sources_dir / f"{source.source_id}.md"
                source_file.write_text(source.to_markdown())
        else:
            self.manifest_path = None

        self.next(self.sync_grok_collection)

    @traced_step
    @step
    def sync_grok_collection(self):
        """Sync to X/Grok Collections API."""
        import asyncio

        if self.skip_grok_sync:
            print("Skipping Grok Collections sync (--skip_grok_sync)")
            self.grok_sync_result = {"skipped": True}
            self.next(self.create_draft)
            return

        print("Syncing to Grok Collections...")

        # Emit progress: summarizing sources for Grok collection
        emit_summarize(self.progress_run_id, len(self.acquired_sources))

        try:
            result = asyncio.get_event_loop().run_until_complete(
                self._sync_to_grok()
            )
        except RuntimeError:
            result = asyncio.new_event_loop().run_until_complete(
                self._sync_to_grok()
            )

        self.grok_sync_result = result
        print(f"Grok sync result: {result}")

        self.next(self.create_draft)

    async def _sync_to_grok(self) -> dict:
        """Sync collection to Grok Collections API using xai-sdk.

        Creates a collection for the article (if needed) and uploads
        all acquired sources as documents.

        Requires XAI_MANAGEMENT_KEY environment variable set with a
        Management API Key that has AddFileToCollection permission.

        Returns:
            Dict with collection_id and upload results

        Raises:
            RuntimeError: If XAI_MANAGEMENT_KEY not set or API calls fail (fail-fast)
        """
        from xai_sdk import Client as XAIClient
        from xai_sdk.collections import FieldDefinition

        from gaius.core.config import get_config as _get_cfg

        mgmt_key = _get_cfg().providers.xai.management_key
        if not mgmt_key:
            raise RuntimeError(
                "XAI_MANAGEMENT_KEY not configured - required for Grok Collections.\n"
                "  Guru Meditation: #ACF.00000011.NOMGMTKEY\n"
                "  Create a Management API Key at https://console.x.ai with AddFileToCollection permission\n"
                "  Set XAI_MANAGEMENT_KEY environment variable"
            )

        if not self.selected_candidate:
            raise RuntimeError(
                "No selected candidate for Grok sync.\n"
                "  Guru Meditation: #ACF.00000004.SELECTFAIL"
            )

        # Use xai-sdk Client (synchronous, will block)
        client = XAIClient(management_api_key=mgmt_key)

        try:
            collection_name = f"gaius-article-{self.selected_candidate.slug}"
            collection_id = None

            # Step 1: Try to find existing collection
            print(f"Checking for existing collection: {collection_name}")
            try:
                collections = client.collections.list()
                for c in collections.collections:
                    if c.collection_name == collection_name:
                        collection_id = c.collection_id
                        print(f"Found existing collection: {collection_id}")
                        break
            except Exception as e:
                logger.warning(f"Failed to list collections: {e}")

            # Step 2: Create collection if not found
            if not collection_id:
                print(f"Creating collection: {collection_name}")
                try:
                    collection = client.collections.create(
                        name=collection_name,
                        model_name="grok-embedding-small",
                        field_definitions=[
                            FieldDefinition(key="source_type", required=False, inject_into_chunk=True, unique=False),
                            FieldDefinition(key="source_id", required=False, inject_into_chunk=False, unique=True),
                            FieldDefinition(key="url", required=False, inject_into_chunk=True, unique=False),
                        ],
                    )
                    collection_id = collection.collection_id
                    print(f"Created collection: {collection_id}")
                except Exception as e:
                    raise RuntimeError(
                        f"Failed to create Grok collection: {e}\n"
                        "  Guru Meditation: #ACF.00000009.NOGROK\n"
                        "  Check Management API key permissions (needs AddFileToCollection)"
                    ) from e

            if not collection_id:
                raise RuntimeError(
                    "Collection ID not returned from xAI API.\n"
                    "  Guru Meditation: #ACF.00000009.NOGROK\n"
                    "  Check xAI Collections API response format"
                )

            # Step 2.5: Persist grok_collection_id to PostgreSQL (1:1 mapping)
            # Fail-fast: if DB persistence fails, the 1:1 mapping is lost.
            # The Grok collection still exists on xAI and can be recovered
            # via /collection reconcile-grok, but we must not silently continue.
            if self.collection_id and not self.dry_run:
                await self._update_grok_collection_id_in_db(collection_id)
                print(f"Persisted grok_collection_id to database: {collection_id}")

            # Step 3: Upload acquired sources as documents
            upload_results = []
            for source in self.acquired_sources:
                # Prepare document content as markdown
                doc_content = f"# {source.title}\n\n"
                doc_content += f"Source: {source.url}\n"
                doc_content += f"Type: {source.source_type}\n\n"
                if source.summary:
                    doc_content += f"## Summary\n{source.summary}\n"

                try:
                    # Upload document using SDK (use .md extension for markdown content type)
                    document = client.collections.upload_document(
                        collection_id=collection_id,
                        name=f"{source.source_id}.md",
                        data=doc_content.encode("utf-8"),
                        fields={
                            "source_type": source.source_type,
                            "source_id": source.source_id,
                            "url": source.url,
                        },
                    )

                    upload_results.append({
                        "source_id": source.source_id,
                        "status": "uploaded",
                        "document_id": getattr(document, "file_id", None),
                    })
                    print(f"Uploaded: {source.source_id}")

                except Exception as e:
                    upload_results.append({
                        "source_id": source.source_id,
                        "status": "failed",
                        "error": str(e)[:100],
                    })
                    logger.warning(f"Failed to upload {source.source_id}: {e}")

            # Fail if no documents were uploaded successfully
            successful_uploads = [r for r in upload_results if r["status"] == "uploaded"]
            if not successful_uploads:
                raise RuntimeError(
                    "No documents were uploaded to Grok collection.\n"
                    "  Guru Meditation: #ACF.00000009.NOGROK\n"
                    f"  Errors: {upload_results}"
                )

            # Step 4: Update manifest with collection_id
            if not self.dry_run:
                manifest_path = Path(self.selected_candidate.kb_path) / "manifest.yaml"
                if manifest_path.exists():
                    manifest = yaml.safe_load(manifest_path.read_text())
                    manifest["grok_collection_id"] = collection_id
                    manifest_path.write_text(yaml.dump(manifest, default_flow_style=False))
                    print(f"Updated manifest with grok_collection_id: {collection_id}")

            return {
                "success": True,
                "collection_id": collection_id,
                "collection_name": collection_name,
                "documents_uploaded": len(successful_uploads),
                "documents_failed": len(upload_results) - len(successful_uploads),
                "upload_results": upload_results,
            }

        finally:
            client.close()

    async def _update_grok_collection_id_in_db(self, grok_collection_id: str) -> None:
        """Persist grok_collection_id to PostgreSQL for 1:1 article-collection mapping.

        This ensures the local PostgreSQL collection record tracks its corresponding
        xAI/Grok collection, enabling reconciliation and status queries.

        Args:
            grok_collection_id: The xAI/Grok collection ID to persist

        Uses self.collection_id (local PostgreSQL collection ID) set in select_article step.
        """
        import asyncpg
        from gaius.core.config import get_database_url
        from gaius.engine.services.collection_service import CollectionService

        db_url = get_database_url()

        pool = await asyncpg.create_pool(db_url, min_size=1, max_size=1)
        try:
            service = CollectionService(pool)
            await service.update_grok_collection_id(
                collection_id=self.collection_id,
                grok_collection_id=grok_collection_id,
            )
        finally:
            await pool.close()

    def _preserve_frontmatter_fields(self, original_path: Path) -> dict:
        """Extract essential frontmatter fields to preserve during draft regeneration.

        Fields like arxiv_categories, keywords, news_queries are used for source
        acquisition and must not be lost when Grok generates a new draft.
        """
        if not original_path.exists():
            return {}

        content = original_path.read_text()

        # Parse YAML frontmatter
        import re

        match = re.match(r"^---\n(.*?)\n---", content, re.DOTALL)
        if not match:
            return {}

        try:
            frontmatter = yaml.safe_load(match.group(1))
        except yaml.YAMLError:
            return {}

        # Fields to preserve (used for source acquisition)
        preserve_keys = ["arxiv_categories", "keywords", "news_queries"]
        return {k: v for k, v in frontmatter.items() if k in preserve_keys and v}

    def _merge_frontmatter(self, draft_content: str, preserved: dict) -> str:
        """Merge preserved fields into generated draft frontmatter."""
        import re

        if not preserved:
            return draft_content

        # Parse the generated draft's frontmatter
        match = re.match(r"^---\n(.*?)\n---\n(.*)$", draft_content, re.DOTALL)
        if not match:
            # No frontmatter in generated draft - add one with preserved fields
            frontmatter = preserved.copy()
            yaml_str = yaml.dump(frontmatter, default_flow_style=False, allow_unicode=True)
            return f"---\n{yaml_str}---\n\n{draft_content}"

        try:
            frontmatter = yaml.safe_load(match.group(1)) or {}
        except yaml.YAMLError:
            frontmatter = {}

        # Merge preserved fields (preserved takes precedence)
        for key, value in preserved.items():
            frontmatter[key] = value

        # Rebuild
        yaml_str = yaml.dump(frontmatter, default_flow_style=False, allow_unicode=True)
        body = match.group(2)
        return f"---\n{yaml_str}---\n{body}"

    @traced_step
    @step
    def create_draft(self):
        """Generate new draft with Grok, archive current to hx/."""
        import asyncio

        print("Creating article draft...")

        if not self.selected_candidate or self.dry_run:
            self.draft_entry = None
            self.next(self.create_base)
            return

        # Preserve essential frontmatter fields BEFORE archiving
        article_path = Path(self.selected_candidate.kb_path) / "article.md"
        preserved_fields = self._preserve_frontmatter_fields(article_path)
        if preserved_fields:
            print(f"Preserving frontmatter fields: {list(preserved_fields.keys())}")

        # Archive current draft to hx/
        self._archive_current_draft()

        # Generate new draft with Grok
        try:
            draft_content = asyncio.get_event_loop().run_until_complete(
                self._generate_draft()
            )
        except RuntimeError:
            draft_content = asyncio.new_event_loop().run_until_complete(
                self._generate_draft()
            )

        # Merge preserved frontmatter fields back into the generated draft
        draft_content = self._merge_frontmatter(draft_content, preserved_fields)

        # Write new draft
        article_path.write_text(draft_content)

        # Create draft entry
        self.draft_entry = DraftHistoryEntry.from_content(
            content=draft_content,
            version=self.selected_candidate.current_version + 1,
            generator_model="grok-4-1-fast",
            generator_run_id=current.run_id if hasattr(current, "run_id") else None,
            parent_version=self.selected_candidate.current_version,
        )

        print(f"Created draft v{self.draft_entry.version}: {self.draft_entry.word_count} words")

        # Emit progress: draft created
        emit_draft(self.progress_run_id, self.draft_entry.word_count)

        self.next(self.create_base)

    def _archive_current_draft(self):
        """Archive current article.md to hx/ directory."""
        if not self.selected_candidate:
            return

        article_path = Path(self.selected_candidate.kb_path) / "article.md"
        if not article_path.exists():
            return

        hx_dir = Path(self.selected_candidate.kb_path) / "hx"
        hx_dir.mkdir(parents=True, exist_ok=True)

        current_content = article_path.read_text()
        archive_filename = DraftHistoryEntry.generate_filename(
            version=self.selected_candidate.current_version or 1
        )
        archive_path = hx_dir / archive_filename

        archive_path.write_text(current_content)
        print(f"Archived current draft to: {archive_path}")

    async def _generate_draft(self) -> str:
        """Generate article draft using Grok.

        Returns:
            Draft content as markdown

        Raises:
            RuntimeError: If draft generation fails (fail-fast)
        """
        from gaius.engine.backends.external.xai_backend import XAIBackend

        backend = XAIBackend()

        if not backend.is_available:
            raise RuntimeError(
                "XAI backend not available - Grok is required for draft generation.\n"
                "  Guru Meditation: #ACF.00000002.NOXAI\n"
                "  Set XAI_API_KEY environment variable"
            )

        # Require at least one source
        if not self.acquired_sources:
            raise RuntimeError(
                "No sources acquired - cannot generate draft without sources.\n"
                "  Guru Meditation: #ACF.00000007.NOSOURCES\n"
                "  Check arXiv fetcher and network connectivity"
            )

        # Build source context with full content for citation tracking
        kb_root = get_kb_root()
        sources_context = []
        for i, source in enumerate(self.acquired_sources[:15], 1):
            # Get the full extracted content if available
            extracted_path = find_extracted_path(kb_root, source.traceable_id or "")
            source_content = ""
            if extracted_path:
                full_path = kb_root / extracted_path
                if full_path.exists():
                    content = full_path.read_text()
                    # Include first 2000 chars of source for citation reference
                    source_content = f"\n    Content excerpt:\n    {content[:2000]}..."

            sources_context.append(
                f"[{i}] {source.title}\n"
                f"    URL: {source.url}\n"
                f"    Summary: {source.summary[:200]}..."
                f"{source_content}"
            )

        system_prompt = """You are a technical writer creating publication-ready articles for an AI research audience.

Article Structure:
1. Hook (1-2 sentences): Why should the reader care right now?
2. Context (1 paragraph): Background needed
3. Main Content (3-5 sections): Deep dive with citations [1], [2], etc.
4. Practical Takeaways (bulleted list)
5. Looking Ahead (1 paragraph)
6. References section

Use markdown. Cite sources using [1], [2] notation.

CRITICAL: In your References section, use this EXACT format for each reference you cite:
[N] Title. URL <!-- ref_start:OFFSET ref_end:OFFSET -->

Where OFFSET is the character position in the source's "Content excerpt" where you found the supporting passage.
For example: [4] Paper Title. https://arxiv.org/... <!-- ref_start:234 ref_end:456 -->

If you didn't use a source, don't include it in References.
Count characters carefully from the "Content excerpt:" line in each source."""

        user_prompt = f"""Write an article about: {self.selected_candidate.title}

Research Summary:
{self.research_summary[:1500]}

Available Sources (with content excerpts for citation):
{chr(10).join(sources_context)}

Create a complete, publication-ready article (1500-2500 words).

IMPORTANT: In References, include <!-- ref_start:N ref_end:M --> comments with the character offsets into each source's content excerpt that you relied on for your citation."""

        response = await backend.complete(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            model="grok-4-1-fast",
            temperature=0.6,
            max_tokens=EXTERNAL_MAX_TOKENS,
        )

        if not response.success:
            raise RuntimeError(
                f"Draft generation failed: {response.error}\n"
                "  Guru Meditation: #ACF.00000003.GROKFAIL\n"
                "  Check XAI API status and quota"
            )

        if not response.content or len(response.content) < 100:
            raise RuntimeError(
                "Draft generation returned empty or too short content.\n"
                "  Guru Meditation: #ACF.00000008.EMPTYDRAFT\n"
                "  Grok may have hit content filters or quota limits"
            )

        # Parse citation provenance from References section
        content = response.content
        self.citation_provenance = self._parse_reference_offsets(content)

        # Strip the HTML comments from the article content for clean output
        import re
        content = re.sub(r"\s*<!--\s*ref_start:\d+\s+ref_end:\d+\s*-->", "", content)

        return content.strip()

    def _parse_reference_offsets(self, content: str) -> dict[int, tuple[int, int]]:
        """Parse ref_start/ref_end from HTML comments in References section.

        Expected format in References:
        [4] Title. URL <!-- ref_start:234 ref_end:456 -->

        Returns:
            Dict mapping reference number to (ref_start, ref_end) offsets in source.
        """
        import re

        provenance: dict[int, tuple[int, int]] = {}

        # Find all reference lines with offset comments
        # Pattern: [N] ... <!-- ref_start:X ref_end:Y -->
        pattern = r"\[(\d{1,2})\][^\n]*<!--\s*ref_start:(\d+)\s+ref_end:(\d+)\s*-->"
        for match in re.finditer(pattern, content):
            ref_num = int(match.group(1))
            ref_start = int(match.group(2))
            ref_end = int(match.group(3))
            provenance[ref_num] = (ref_start, ref_end)
            print(f"  [{ref_num}] source offset: {ref_start}-{ref_end}")

        if not provenance:
            print("No ref_start/ref_end comments found in References")

        return provenance

    @traced_step
    @step
    def create_base(self):
        """Create BFO-grounded Base file with ref_start/ref_end offsets and brief summaries.

        Output format:
        - Filename: {HHMMSS}_{slug}.base (zettelkasten naming)
        - Contains @context with Gaius ontology prefixes
        - References grounded to IAO:0000300 (textual entity)
        - ref_start/ref_end point to the cited passage in the SOURCE document
          (populated from citation_provenance extracted during draft generation)
        - brief_summary: LLM-generated summary of the cited passage

        OTel Metrics:
        - article_curation.citation.offset.specific: Count of refs with specific offsets
        - article_curation.citation.offset.general: Count of refs using whole source
        """
        import asyncio

        print("Creating BFO Base file...")

        if not self.selected_candidate or self.dry_run:
            self.base_path = None
            self.cards_created = 0
            self.next(self.end)
            return

        # Get citation provenance from draft generation (set by _generate_draft)
        citation_provenance: dict[int, tuple[int, int]] = getattr(self, "citation_provenance", {})
        print(f"Using citation provenance for {len(citation_provenance)} references")

        # Build references from acquired sources
        kb_root = get_kb_root()
        references = []

        # Collect source content for brief_summary generation
        # We'll batch-generate summaries via one Grok call
        source_content_for_summary: list[tuple[int, str, bool]] = []  # (ref_num, content, has_specific_offset)

        # OTel metrics
        specific_offset_count = 0
        general_offset_count = 0

        for i, source in enumerate(self.acquired_sources[:20], 1):
            # Find extracted markdown for this source
            extracted_path = find_extracted_path(kb_root, source.traceable_id or "")

            # Get provenance offsets from Grok's citation tracking
            ref_start, ref_end = citation_provenance.get(i, (-1, -1))

            ref = ArticleReference(
                ref_id=f"ref_{i:03d}",
                source_id=source.source_id,
                traceable_id=source.traceable_id or "",
                ref_start=ref_start,
                ref_end=ref_end,
                excerpt=source.summary[:200] if source.summary else "",
                title=source.title or "",
                extracted_path=extracted_path,
            )
            references.append(ref)

            # Determine content for brief_summary
            has_specific_offset = ref_start >= 0 and ref_end > ref_start
            if has_specific_offset:
                specific_offset_count += 1
                # Get the specific cited passage from extracted content
                content = ""
                if extracted_path:
                    full_path = kb_root / extracted_path
                    if full_path.exists():
                        full_content = full_path.read_text()
                        # Extract the offset-delimited passage
                        if ref_end <= len(full_content):
                            content = full_content[ref_start:ref_end]
                        else:
                            # Offset out of bounds - use whole summary as fallback
                            content = source.summary[:500] if source.summary else ""
                            has_specific_offset = False  # Mark as general for metrics
                            general_offset_count += 1
                            specific_offset_count -= 1
                if not content:
                    content = source.summary[:500] if source.summary else ""
                print(f"  [{i}] cites source passage at chars {ref_start}-{ref_end} ({len(content)} chars)")
            else:
                general_offset_count += 1
                # Use the whole source summary
                content = source.summary[:500] if source.summary else source.title
                print(f"  [{i}] uses whole source (no specific offset)")

            source_content_for_summary.append((i, content, has_specific_offset))

        # Emit OTel metrics for offset specificity tracking
        self.emit_event("article_curation.citation.offset.specific", {
            "count": specific_offset_count,
            "slug": self.selected_candidate.slug,
        })
        self.emit_event("article_curation.citation.offset.general", {
            "count": general_offset_count,
            "slug": self.selected_candidate.slug,
        })
        print(f"Citation specificity: {specific_offset_count} specific, {general_offset_count} general")

        # Generate brief summaries via Grok (batched in one request)
        if source_content_for_summary:
            try:
                summaries = asyncio.get_event_loop().run_until_complete(
                    self._generate_brief_summaries(source_content_for_summary)
                )
            except RuntimeError:
                summaries = asyncio.new_event_loop().run_until_complete(
                    self._generate_brief_summaries(source_content_for_summary)
                )

            # Apply summaries to references
            for i, summary in summaries.items():
                if 1 <= i <= len(references):
                    references[i - 1].brief_summary = summary

        # Build base file content with @context
        # Uses JSON-LD style context for semantic grounding
        base_content = {
            "type": "article-base",
            "version": 1,
            "slug": self.selected_candidate.slug,
            "title": self.selected_candidate.title,
            "@context": {
                "@vocab": "https://gaius.zndx.dev/ontology/article/",
                "gaius": "https://gaius.zndx.dev/ontology/",
                "BFO": "http://purl.obolibrary.org/obo/BFO_",
                "IAO": "http://purl.obolibrary.org/obo/IAO_",
                "obo": "http://purl.obolibrary.org/obo/",
                "dct": "http://purl.org/dc/terms/",
                "schema": "https://schema.org/",
                # Term mappings
                "ref_id": {"@id": "gaius:referenceId", "@type": "xsd:string"},
                "source_id": {"@id": "gaius:sourceId", "@type": "xsd:string"},
                "traceable_id": {"@id": "gaius:traceableId", "@type": "xsd:anyURI"},
                "ref_start": {"@id": "gaius:referenceStart", "@type": "xsd:integer"},
                "ref_end": {"@id": "gaius:referenceEnd", "@type": "xsd:integer"},
                "excerpt": {"@id": "IAO:0000300", "@type": "xsd:string"},  # textual entity
                "brief_summary": {
                    "@id": "gaius:briefSummary",
                    "@type": "xsd:string",
                    "description": "LLM-generated summary of the cited passage or whole source",
                },
                "iao_type": {"@id": "rdf:type"},
                "card_status": {
                    "@id": "gaius:cardStatus",
                    "@type": "xsd:string",
                    "description": "Publication status: unknown, pending, published, skipped, archived",
                },
                "extracted_path": {
                    "@id": "gaius:extractedPath",
                    "@type": "xsd:string",
                    "description": "Relative path to OCR-extracted markdown (docling output)",
                },
            },
            "ontology": {
                "base": "https://gaius.zndx.dev/ontology/article/",
                "imports": [
                    "http://purl.obolibrary.org/obo/bfo.owl",
                    "http://purl.obolibrary.org/obo/iao.owl",
                ],
            },
            "references": [r.to_dict() for r in references],
            "created_at": datetime.now().isoformat(),
        }

        yaml_content = yaml.dump(base_content, default_flow_style=False, allow_unicode=True)
        base_file_content = f"---\n{yaml_content}---\n"

        # Zettelkasten naming: HHMMSS_slug.base
        timestamp = datetime.now().strftime("%H%M%S")
        base_filename = f"{timestamp}_{self.selected_candidate.slug}.base"
        base_path = Path(self.selected_candidate.kb_path) / base_filename
        base_path.write_text(base_file_content)
        self.base_path = str(base_path)

        print(f"Created base file with {len(references)} references: {base_path}")

        # Emit progress: base file created
        emit_base(self.progress_run_id, str(base_path), len(references))

        self.next(self.create_cards)

    async def _generate_brief_summaries(
        self, sources: list[tuple[int, str, bool]]
    ) -> dict[int, str]:
        """Generate brief summaries for source passages via Grok.

        Uses a single Grok API call to generate summaries for all sources
        in batch for efficiency.

        Args:
            sources: List of (ref_num, content, has_specific_offset) tuples

        Returns:
            Dict mapping ref_num to brief summary string
        """
        from gaius.engine.backends.external.xai_backend import XAIBackend

        backend = XAIBackend()

        if not backend.is_available:
            raise RuntimeError(
                "XAI backend not available for brief summary generation.\n"
                "  Guru Meditation: #ACF.00000018.XAINOTAVAIL\n"
                "  Try: /health fix endpoints\n"
                "  Or:  Ensure XAI_API_KEY is configured"
            )

        # Build batch prompt
        sources_text = []
        for ref_num, content, has_specific in sources:
            source_type = "cited passage" if has_specific else "source abstract"
            sources_text.append(f"[{ref_num}] ({source_type}):\n{content[:600]}")

        prompt = f"""Generate brief 1-2 sentence summaries for each of the following source passages.
For each, state the key contribution or finding in concrete terms.

{chr(10).join(sources_text)}

Respond with JSON:
{{
  "1": "Brief summary of source 1...",
  "2": "Brief summary of source 2...",
  ...
}}

Be concise - each summary should be 1-2 sentences max."""

        try:
            response = await backend.complete(
                messages=[
                    {"role": "system", "content": "You generate concise summaries for academic source citations."},
                    {"role": "user", "content": prompt},
                ],
                model="grok-4-1-fast",
                temperature=0.3,
                max_tokens=EXTERNAL_MAX_TOKENS,
            )

            if not response.success or not response.content:
                raise RuntimeError(
                    f"Brief summary API call failed: {response.error}\n"
                    "  Guru Meditation: #ACF.00000019.BRIEFSUMFAIL\n"
                    "  Try: /health fix endpoints\n"
                    "  Or:  Check XAI backend availability"
                )

            # Parse JSON response
            content = response.content
            start = content.find("{")
            end = content.rfind("}") + 1
            if start < 0 or end <= start:
                raise RuntimeError(
                    "Brief summary response contains no JSON object.\n"
                    "  Guru Meditation: #ACF.00000020.BRIEFSUMPARSE\n"
                    f"  Response preview: {content[:200]}"
                )
            summaries_raw = json.loads(content[start:end])
            # Convert string keys to int
            return {int(k): v for k, v in summaries_raw.items() if k.isdigit()}

        except json.JSONDecodeError as e:
            raise RuntimeError(
                f"Brief summary response parse error: {e}\n"
                "  Guru Meditation: #ACF.00000020.BRIEFSUMPARSE\n"
                "  The XAI response was not valid JSON"
            ) from e

    @traced_step
    @step
    def create_cards(self):
        """Create collection cards from .base file references.

        Cards are created with status 'pending' - they are NOT published yet.
        Use /publish cards to promote pending cards to the landing page.

        This step runs after create_base and:
        1. Parses the just-created .base file
        2. Creates a card for each reference with brief_summary
        3. Updates card_status in .base file from unknown -> pending

        Fail-fast if:
        - Article not in database (should have been registered in select_article)
        - Missing collection mapping (1:1 article-collection enforced)
        - Missing brief_summary for any reference
        """
        print("Creating collection cards from .base file...")

        if not self.base_path or self.dry_run:
            self.cards_created = 0
            self.created_card_ids = []
            self.next(self.enrich_cards)
            return

        try:
            card_ids, ref_ids = asyncio.get_event_loop().run_until_complete(
                self._create_cards_async()
            )
        except RuntimeError:
            card_ids, ref_ids = asyncio.new_event_loop().run_until_complete(
                self._create_cards_async()
            )

        self.cards_created = len(card_ids)
        self.created_card_ids = card_ids
        print(f"Created {self.cards_created} cards (all pending)")

        # Update .base file: unknown -> pending
        if ref_ids:
            base_path = Path(self.base_path)
            ref_updates = {ref_id: CardStatus.PENDING for ref_id in ref_ids}
            updated = update_base_file(base_path, ref_updates)
            print(f"Updated {updated} references to pending status")

        self.emit_event("article_curation.cards.created", {
            "slug": self.selected_slug,
            "cards_created": self.cards_created,
        })

        # Emit progress: cards created
        emit_cards(self.progress_run_id, self.cards_created)

        self.next(self.enrich_cards)

    async def _create_cards_async(self) -> tuple[list[str], list[str]]:
        """Create cards with full provenance via CollectionService.

        For each reference in the .base file:
        1. Creates the card with metadata (zettle_slug, kb_path)
        2. Creates a Source record linking the card to its provenance

        Both operations must succeed — if Source creation fails after
        card creation, the error propagates (fail-fast). The card will
        exist without a source, which is detectable and repairable.

        Returns:
            Tuple of (card_ids, ref_ids) for created cards

        Raises:
            RuntimeError: On schema mismatch or missing required data
        """
        import asyncpg
        from gaius.core.config import get_database_url
        from gaius.engine.services.collection_service import CollectionService

        if not self.base_path:
            return [], []

        base_path = Path(self.base_path)
        data, references = parse_base_file(base_path)

        db_url = get_database_url()

        async with asyncpg.create_pool(db_url, min_size=1, max_size=3) as pool:
            service = CollectionService(pool)

            # Use article_id and collection_id from select_article step
            if not self.article_id or not self.collection_id:
                raise RuntimeError(
                    "Article not registered in database.\n"
                    "  Guru Meditation: #ACF.00000014.NOARTICLE\n"
                    "  This should not happen - article is registered in select_article step"
                )

            # zettle_slug comes from the selected article
            zettle_slug = self.selected_slug if hasattr(self, "selected_slug") else None
            if not zettle_slug:
                raise RuntimeError(
                    "Missing selected_slug for card metadata.\n"
                    "  Guru Meditation: #ACF.00000017.NOSLUG\n"
                    "  This should not happen - slug is set in select_article step"
                )

            card_ids: list[str] = []
            ref_ids: list[str] = []

            for ref in references:
                # Skip if already has a card (card_status != unknown)
                if ref.card_status != CardStatus.UNKNOWN:
                    continue

                source_url = traceable_id_to_url(ref.traceable_id)
                source_type = extract_source_type(ref.traceable_id)

                # Validate source URL before creating card
                self._validate_source_url(source_url, ref.ref_id, ref.traceable_id)

                # One card per source URL across ALL articles. acquired_sources is
                # unique per (article, url) only, so the same page acquired by
                # different articles became several published cards with identical
                # briefs (agentic.ai listicle x4, medium.com x2 — the
                # #SITE.00000003.BRIEFS duplicates, 2026-09-06).
                dup = await pool.fetchval(
                    "SELECT card_id FROM collections.cards WHERE source_url = $1 LIMIT 1",
                    source_url,
                )
                if dup:
                    print(f"  skip {ref.ref_id}: {source_url[:70]} already has card {dup}")
                    continue

                brief_summary = ref.brief_summary or ""
                if not brief_summary:
                    raise RuntimeError(
                        f"Missing brief_summary for {ref.ref_id}.\n"
                        "  Guru Meditation: #ACF.00000015.NOBRIEFSUMMARY\n"
                        "  Fix: Check .base file generation in create_base step"
                    )

                # Use source title (arXiv paper title, etc.)
                # Fall back to brief_summary first sentence only if no title
                card_title = ref.title or ""
                if not card_title:
                    card_title = self._extract_card_title(brief_summary)
                if not card_title:
                    raise RuntimeError(
                        f"Missing title for {ref.ref_id}.\n"
                        "  Guru Meditation: #ACF.00000016.NOTITLE\n"
                        "  Fix: Check source fetcher provides title"
                    )

                # KB path to the source file on disk
                source_kb_path = f"current/articles/{zettle_slug}/sources/{ref.source_id}.md"

                # Carry the source's publication date onto the card. The
                # content_currency intent objective reads source_date; every
                # curation batch before 2026-09-03 left it NULL and the
                # objective could not see curated inflow at all.
                source_date = None
                try:
                    from gaius.flows.article_curation.common import (
                        _parse_frontmatter,
                        source_date_from_frontmatter,
                    )

                    src_text = (get_kb_root() / source_kb_path).read_text(encoding="utf-8")
                    source_date = source_date_from_frontmatter(_parse_frontmatter(src_text))
                except Exception as e:  # noqa: BLE001 — a date is metadata; the card still lands
                    print(f"  {ref.ref_id}: source_date unavailable ({e}); leaving NULL")
                if source_date is None:
                    # (2026-09-07) arXiv papers arriving as web results carry no
                    # frontmatter date; the identifier's month is an honest lower
                    # bound. Still None → the card stays pending at publish time
                    # (an undated card never reaches the surface).
                    from gaius.flows.article_curation.common import source_date_from_url

                    source_date = source_date_from_url(source_url)
                    if source_date is not None:
                        print(f"  {ref.ref_id}: source_date {source_date} from the arXiv id month (lower bound)")

                card = await service.add_card(
                    collection_id=self.collection_id,
                    title=card_title,
                    summary=brief_summary,
                    source_url=source_url,
                    source_type=source_type,
                    source_date=source_date,
                    article_id=self.article_id,
                    kb_path=source_kb_path,
                    zettle_slug=zettle_slug,
                )

                # Create provenance source record — fail-fast
                excerpt_char_start = ref.ref_start if ref.ref_start >= 0 else None
                excerpt_char_end = ref.ref_end if ref.ref_end >= 0 else None

                await service.add_source(
                    source_id=ref.ref_id,
                    card_id=card.card_id,
                    provenance_url=source_url,
                    source_type=source_type,
                    provenance_traceable_id=ref.traceable_id,
                    excerpt_text=ref.excerpt if ref.excerpt else None,
                    excerpt_char_start=excerpt_char_start,
                    excerpt_char_end=excerpt_char_end,
                    ingested_via="article_curation",
                    kb_path=source_kb_path,
                )

                card_ids.append(card.card_id)
                ref_ids.append(ref.ref_id)

            return card_ids, ref_ids

    @staticmethod
    def _validate_source_url(url: str, ref_id: str, traceable_id: str) -> None:
        """Validate source URL before card creation.

        Rejects empty, placeholder, and unparseable URLs to prevent
        broken cards from entering the database.

        Raises:
            RuntimeError: If the URL is invalid or a known placeholder
        """
        import re
        from urllib.parse import urlparse

        if not url or not url.strip():
            raise RuntimeError(
                f"Empty source URL for {ref_id} (traceable_id={traceable_id}).\n"
                "  Guru Meditation: #ACF.00000021.BADURL\n"
                "  Fix: Check traceable_id_to_url() conversion"
            )

        # Reject known placeholder patterns
        placeholder_patterns = [
            r"2501\.00000",       # Fake arXiv ID from test scripts
            r"example\.com",      # Generic placeholder domain
            r"placeholder",       # Explicit placeholder
        ]
        for pattern in placeholder_patterns:
            if re.search(pattern, url, re.IGNORECASE):
                raise RuntimeError(
                    f"Placeholder URL detected for {ref_id}: {url}\n"
                    "  Guru Meditation: #ACF.00000021.BADURL\n"
                    "  Fix: Ensure source has a real traceable_id, not test data"
                )

        # Basic URL structure check
        parsed = urlparse(url)
        if not parsed.scheme or not parsed.netloc:
            raise RuntimeError(
                f"Malformed URL for {ref_id}: {url}\n"
                "  Guru Meditation: #ACF.00000021.BADURL\n"
                "  Fix: URL must have scheme and host"
            )

    def _extract_card_title(self, content: str) -> str:
        """Extract title from brief_summary content.

        Uses first sentence (up to first period), max 80 chars.

        Args:
            content: Brief summary text

        Returns:
            Title string (max 80 chars)
        """
        if not content:
            return ""

        # Get first sentence (up to first period)
        first_line = content.strip().split("\n")[0]
        sentences = first_line.split(". ")
        title = sentences[0] if sentences else first_line

        # Strip markdown markers
        if title.startswith("#"):
            title = title.lstrip("#").strip()

        # Truncate to 80 chars
        if len(title) > 80:
            return title[:77] + "..."

        return title

    @traced_step
    @step
    def enrich_cards(self):
        """Enrich cards with summaries and images BEFORE publishing.

        For each card created in this run:
        1. Local open-weights summary (required) plus Brave/Cerebras if up
        2. Render LuxCore visualization via gRPC RenderCards

        Cards that pass all enrichment are tracked in self.enriched_card_ids.
        Cards that fail any enrichment step stay pending (not published).

        Fail-fast: If ALL cards fail enrichment, the step raises with
        #ACF.00000022.NOENRICHED. Partial success is OK.
        """
        created_card_ids = getattr(self, "created_card_ids", [])

        if not created_card_ids or self.dry_run:
            print("No cards to enrich, skipping enrich_cards")
            self.enriched_card_ids = []
            self.enrichment_failures = {}
            self.next(self.publish_batch)
            return

        print(f"Enriching {len(created_card_ids)} cards (summaries + images)...")

        try:
            enriched, failures = asyncio.get_event_loop().run_until_complete(
                self._enrich_cards_async(created_card_ids)
            )
        except RuntimeError:
            enriched, failures = asyncio.new_event_loop().run_until_complete(
                self._enrich_cards_async(created_card_ids)
            )

        self.enriched_card_ids = enriched
        self.enrichment_failures = failures

        print(f"Enrichment complete: {len(enriched)} enriched, {len(failures)} failed")
        if failures:
            for cid, reason in failures.items():
                print(f"  FAILED {cid}: {reason}")

        # Fail-fast if ALL cards failed enrichment
        if not enriched and created_card_ids:
            raise RuntimeError(
                f"All {len(created_card_ids)} cards failed enrichment.\n"
                "  Guru Meditation: #ACF.00000022.NOENRICHED\n"
                "  Try: /health fix endpoints\n"
                f"  Failures: {failures}"
            )

        emit_enrich(self.progress_run_id, len(enriched), len(failures))

        self.next(self.publish_batch)

    async def _enrich_cards_async(
        self, card_ids: list[str]
    ) -> tuple[list[str], dict[str, str]]:
        """Enrich cards with summaries and images.

        For each card:
        1. Local open-weights required; Brave/Cerebras optional (API/budget)
        2. LuxCore image via gRPC RenderCards — required

        Args:
            card_ids: Card IDs to enrich

        Returns:
            Tuple of (enriched_card_ids, failures dict of card_id → reason)
        """
        import asyncpg
        from gaius.core.config import get_database_url
        from gaius.engine.services.collection_service import (
            OPTIONAL_CARD_SUMMARIES,
            REQUIRED_CARD_SUMMARY,
            CollectionService,
        )

        db_url = get_database_url()
        enriched: list[str] = []
        failures: dict[str, str] = {}

        async with asyncpg.create_pool(db_url, min_size=1, max_size=3) as pool:
            service = CollectionService(pool)

            for i, card_id in enumerate(card_ids):
                card_label = f"[{i + 1}/{len(card_ids)}] {card_id[:12]}"
                card_failed = False

                # --- Summaries ---
                for summary_type in (REQUIRED_CARD_SUMMARY, *OPTIONAL_CARD_SUMMARIES):
                    try:
                        await service.generate_card_summary(card_id, summary_type)
                        print(f"  {card_label}: {summary_type} OK")
                    except Exception as e:
                        print(f"  {card_label}: {summary_type} FAILED - {e}")
                        if summary_type in OPTIONAL_CARD_SUMMARIES:
                            continue
                        failures[card_id] = f"{summary_type}: {e}"
                        card_failed = True
                        break

                if card_failed:
                    continue

                # --- Image rendering via gRPC ---
                try:
                    await self._render_card_image(card_id, card_label)
                except Exception as e:
                    print(f"  {card_label}: render FAILED - {e}")
                    failures[card_id] = f"render: {e}"
                    continue

                # --- Sync card page to KV (summaries + image now present) ---
                try:
                    await service.sync_card_to_kv(card_id)
                    print(f"  {card_label}: KV sync OK")
                except Exception as e:
                    # KV sync failure is non-fatal for enrichment — card content is in DB
                    print(f"  {card_label}: KV sync FAILED (non-fatal) - {e}")

                enriched.append(card_id)

        return enriched, failures

    async def _render_card_image(self, card_id: str, card_label: str) -> None:
        """Render a single card's image via gRPC RenderCards.

        Args:
            card_id: Card to render
            card_label: Label for log messages

        Raises:
            Exception: If rendering fails
        """
        from gaius.client.grpc_client import get_grpc_client, GrpcClientConfig

        client = await get_grpc_client(GrpcClientConfig.for_cli())

        async for event in client.RenderCards(
            card_id=card_id,
            upload=True,
        ):
            if event.message:
                print(f"  {card_label}: render - {event.message}")
            if event.error:
                raise RuntimeError(f"Render error: {event.error}")
            if event.image_url:
                print(f"  {card_label}: image OK ({event.image_url})")

    @traced_step
    @step
    def publish_batch(self):
        """Publish enriched cards and sync all KV stores.

        Only cards that passed enrichment (summaries + images) get published.
        This ensures no cards with missing content appear on gaius.zndx.org.

        Operations (all fail-fast):
        1. publish_cards_by_ids() — promote enriched cards to published
        2. sync_to_kv() — update landing page published_cards key
        3. sync_collection_to_kv() — update collection detail page
        4. sync_collections_index_to_kv() — update /collections index
        """
        enriched_card_ids = getattr(self, "enriched_card_ids", [])

        if not enriched_card_ids:
            print("No enriched cards to publish, skipping publish_batch")
            self.published_count = 0
            self.next(self.end)
            return

        print(f"Publishing {len(enriched_card_ids)} enriched cards and syncing KV stores...")

        try:
            published_count = asyncio.get_event_loop().run_until_complete(
                self._publish_batch_async(enriched_card_ids)
            )
        except RuntimeError:
            published_count = asyncio.new_event_loop().run_until_complete(
                self._publish_batch_async(enriched_card_ids)
            )

        self.published_count = published_count
        print(f"Published {published_count} enriched cards, KV stores synced")

        self.emit_event("article_curation.published", {
            "slug": self.selected_slug,
            "published_count": published_count,
        })

        emit_publish(self.progress_run_id, published_count)

        self.next(self.end)

    async def _publish_batch_async(self, enriched_card_ids: list[str]) -> int:
        """Publish enriched cards by ID and sync KV stores.

        Args:
            enriched_card_ids: Card IDs that passed enrichment

        Returns:
            Number of cards actually published

        Raises:
            RuntimeError: If any step fails
        """
        import asyncpg
        from gaius.core.config import get_database_url
        from gaius.engine.services.collection_service import CollectionService

        db_url = get_database_url()

        async with asyncpg.create_pool(db_url, min_size=1, max_size=3) as pool:
            service = CollectionService(pool)

            # 1. Publish only enriched cards by explicit IDs
            published = await service.publish_cards_by_ids(enriched_card_ids)
            published_count = len(published)
            print(f"  publish_cards_by_ids: {published_count} cards promoted to published")

            # 2. Sync landing page KV (published_cards key)
            sync_result = await service.sync_to_kv()
            print(f"  sync_to_kv: {sync_result.get('cards_synced', 0)} cards synced")

            # 3. Sync collection detail page KV
            col_result = await service.sync_collection_to_kv(self.collection_id)
            print(f"  sync_collection_to_kv: {col_result.get('cards_synced', 0)} cards")

            # 4. Sync collections index page KV
            idx_result = await service.sync_collections_index_to_kv()
            print(f"  sync_collections_index_to_kv: {idx_result.get('collections_synced', 0)} collections")

            return published_count

    @traced_step
    @step
    def end(self):
        """Emit lineage and report results."""
        from gaius.hx.lineage.events import Dataset

        # Emit lineage COMPLETE
        outputs = []
        if self.selected_candidate:
            outputs.append(Dataset.from_kb(self.selected_candidate.kb_path))
        if self.base_path:
            outputs.append(Dataset.from_kb(self.base_path))
        cot = getattr(self, "cot_record", None) or {}
        if cot.get("id"):
            # The retained reasoning trace is an output dataset of this run.
            outputs.append(Dataset.from_hx(cot["id"], table=cot.get("table_identifier", "hx.cot_reasoning")))

        self.emit_lineage_complete(outputs=outputs)

        # Publish the run to the Signals data-product inventory
        # (gaius.curation.cot_reasoning: tx + details + hx_reasoning), so the
        # complete product with history is surfaced federation-wide.
        if cot.get("id"):
            # Absolute: Metaflow re-executes this file BY PATH per step task (no
            # parent package), so a relative import here raises ImportError at `end`.
            from gaius.flows.article_curation.publish import publish_from_flow

            published = publish_from_flow(self)
            if published.get("skipped"):
                print("Product publish skipped (Signals warehouse not required)")
            elif published.get("warehouse_error"):
                print(f"Product publish: History JSONL only — {published['warehouse_error']}")
            else:
                print(
                    f"Published {published.get('product_id')} tx={published.get('tx_id')} "
                    f"({published.get('assessment') or 'recorded'})"
                )

        # Summary
        print("\n" + "=" * 60)
        print("ARTICLE CURATION COMPLETE")
        print("=" * 60)

        if self.selected_candidate:
            print(f"Article: {self.selected_candidate.title}")
            print(f"Slug: {self.selected_candidate.slug}")
            print(f"Sources acquired: {len(self.acquired_sources)}")
            if self.draft_entry:
                print(f"Draft version: {self.draft_entry.version}")
                print(f"Word count: {self.draft_entry.word_count}")
            print(f"Base file: {self.base_path}")
            cards_created = getattr(self, 'cards_created', 0)
            enriched_count = len(getattr(self, 'enriched_card_ids', []))
            failures = getattr(self, 'enrichment_failures', {})
            published_count = getattr(self, 'published_count', 0)
            print(f"Cards created: {cards_created}")
            print(f"Cards enriched: {enriched_count}")
            if failures:
                print(f"Cards failed enrichment: {len(failures)}")
                for cid, reason in list(failures.items())[:3]:
                    print(f"  {cid}: {reason}")
            print(f"Cards published: {published_count}")
            print(f"Grok sync: {'Success' if self.grok_sync_result.get('success') else 'Fallback mode'}")

        self.emit_event("article_curation.completed", {
            "slug": self.selected_slug,
            "sources_count": len(self.acquired_sources),
            "draft_version": self.draft_entry.version if self.draft_entry else None,
            "cards_created": getattr(self, "cards_created", 0),
            "cards_enriched": len(getattr(self, "enriched_card_ids", [])),
            "enrichment_failures": len(getattr(self, "enrichment_failures", {})),
            "published_count": getattr(self, "published_count", 0),
        })

        # Emit progress: flow completed
        emit_complete(
            self.progress_run_id,
            self.selected_slug,
            len(self.acquired_sources),
            getattr(self, "cards_created", 0),
        )


if __name__ == "__main__":
    # Apply Metaflow config before running
    from gaius.flows.config import apply_metaflow_config
    apply_metaflow_config()
    ArticleCurationFlow()
