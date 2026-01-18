"""SearchFlow - Multi-phase search with Metaflow orchestration.

Implements a robust, production-ready search workflow:
1. BM25 lexical search (KB)
2. Vector search (ColNomic MaxSim - evicts instruct)
3. Web search (Brave API)
4. Ensure instruct endpoint restored
5. Parallel synthesis (local + Grok branch/join)
6. Merge results and write KB zettelkasten

Progress events are printed to stdout for SearchWorkloadService to parse
and stream as gRPC SearchFlowEvent messages to the TUI.

Usage:
    # Via CLI (preferred)
    uv run gaius-cli --cmd "/search flatbuffers"
    uv run gaius-cli --cmd "/search --local flatbuffers"

    # Direct Metaflow
    uv run python src/gaius/flows/search/flow.py run --query "flatbuffers"
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from metaflow import FlowSpec, Parameter, step

from gaius.agents.metaagent.telemetry import TracedFlow, traced_step
from gaius.flows import register_flow
from gaius.flows.base import GaiusFlow, safe_filename
from gaius.flows.config import apply_metaflow_config
from gaius.hx.lineage.events import Dataset

logger = logging.getLogger(__name__)


@register_flow("search")
class SearchFlow(TracedFlow, GaiusFlow):
    """Multi-phase search with parallel synthesis.

    Steps:
    1. start → Initialize and emit lineage
    2. bm25_search → Lexical KB search
    3. vector_search → ColNomic MaxSim (evicts instruct endpoint)
    4. web_search → Brave API
    5. ensure_instruct → Restore instruct endpoint
    6. BRANCH: local_synthesis ↔ grok_synthesis (parallel)
    7. JOIN: merge_syntheses → Combine results
    8. write_kb → Create zettelkasten
    9. end → Report and emit lineage

    Progress events printed to stdout match SearchFlowEvent types.
    """

    query = Parameter(
        "query",
        help="Search query",
        required=True,
    )

    skip_grok = Parameter(
        "skip_grok",
        help="Skip Grok synthesis (--local mode)",
        default=False,
        type=bool,
    )

    bm25_limit = Parameter(
        "bm25_limit",
        help="BM25 result limit",
        default=10,
        type=int,
    )

    vector_limit = Parameter(
        "vector_limit",
        help="Vector search result limit",
        default=10,
        type=int,
    )

    web_limit = Parameter(
        "web_limit",
        help="Web search result limit",
        default=5,
        type=int,
    )

    @traced_step
    @step
    def start(self):
        """Initialize search and emit lineage START."""
        print("search.queued")

        self.emit_event("search.started", {
            "query": self.query,
            "skip_grok": self.skip_grok,
            "correlation_id": self.get_correlation_id(),
        })

        logger.info(f"SearchFlow starting: query='{self.query}', skip_grok={self.skip_grok}")

        # Initialize result containers
        self.bm25_results: list[dict] = []
        self.vector_results: list[dict] = []
        self.web_results: list[dict] = []
        self.local_result: dict | None = None
        self.grok_result: dict | None = None
        self.kb_path: str = ""

        # Timing metrics
        self.timing: dict[str, float] = {}

        # Emit lineage START
        inputs = [Dataset(namespace="gaius.query", name=self.query)]
        self.emit_lineage_start(job_name="search_flow", inputs=inputs)

        self.next(self.bm25_search)

    @traced_step
    @step
    def bm25_search(self):
        """Phase 1: BM25 lexical search on KB."""
        print("search.bm25.started")
        start = time.time()

        try:
            from gaius.inference.search import get_kb_search

            kb_search = get_kb_search()
            if kb_search.index_size == 0:
                kb_search.build_index()

            results = kb_search.search(self.query, top_k=self.bm25_limit)
            self.bm25_results = [
                {
                    "path": r.path,
                    "title": r.title,
                    "score": r.score,
                    "excerpt": r.snippet[:200] if r.snippet else "",
                }
                for r in results
            ]
            print(f"search.bm25.completed count={len(self.bm25_results)}")

        except ImportError as e:
            # BM25 requires rank_bm25 - fail-fast with Guru code
            raise RuntimeError(
                f"BM25 search unavailable: {e}\n"
                "  Guru Meditation: #SF.00000003.BM25UNAVAIL\n"
                "  Install: uv sync --extra search"
            ) from e
        except Exception as e:
            logger.warning(f"BM25 search error: {e}")
            print(f"search.bm25.completed count=0 (error: {e})")

        self.timing["bm25"] = time.time() - start
        self.next(self.vector_search)

    @traced_step
    @step
    def vector_search(self):
        """Phase 2: ColNomic MaxSim vector search with Phase Change coordination.

        Phase Change Pattern: Ensures ColNomic model is loaded and HEALTHY
        before executing search. This provides resilient dynamic workload
        coordination following the Ambient workload reliability model.

        This step evicts the instruct endpoint to load ColNomic embeddings.
        The ensure_instruct step must restore it before synthesis.
        """
        print("search.vector.started")
        start = time.time()

        async def do_vector_search():
            from gaius.client import get_grpc_client

            client = await get_grpc_client()

            # NOTE: Vector search uses ColNomic embeddings on Qdrant, which doesn't
            # require vLLM endpoint coordination. Phase Change Pattern is NOT needed
            # here - it's for instruct/reasoning model transitions with GPU sharing.

            # Execute vector search directly - ColNomic runs on Qdrant
            async for event in client.stream(
                service="Search",
                action="semantic_stream",
                params={
                    "query": self.query,
                    "limit": self.vector_limit,
                    "use_maxsim": True,
                },
                timeout=60.0,  # Search should be fast once model is ready
            ):
                phase = event.get("phase", "UNKNOWN")
                message = event.get("message", "")

                if phase == "LOADING":
                    print("search.vector.loading")
                elif phase == "SEARCHING":
                    print("search.vector.searching")
                elif phase == "COMPLETE":
                    results = event.get("results", [])
                    return [
                        {
                            "path": r.get("path", ""),
                            "title": r.get("title", ""),
                            "score": r.get("score", 0.0),
                            "excerpt": r.get("excerpt", "")[:200],
                        }
                        for r in results
                    ]
                elif phase == "ERROR":
                    # Fail-open for Qdrant errors - continue with empty results
                    logger.warning(f"Vector search error (fail-open): {message}")
                    return []

            return []

        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                self.vector_results = loop.run_until_complete(do_vector_search())
            finally:
                loop.close()

            print(f"search.vector.completed count={len(self.vector_results)}")

        except Exception as e:
            # Fail-open for vector search - continue with BM25 results
            logger.warning(f"Vector search failed (fail-open): {e}")
            print(f"search.vector.completed count=0 (error: {e})")

        self.timing["vector"] = time.time() - start
        self.next(self.web_search)

    @traced_step
    @step
    def web_search(self):
        """Phase 3: Web search via Brave API."""
        print("search.web.started")
        start = time.time()

        async def do_web_search():
            try:
                from gaius.inference import get_search

                search = get_search()
                results = await search.search(self.query, count=self.web_limit)

                return [
                    {
                        "title": r.title,
                        "url": r.url,
                        "snippet": (r.snippet[:300] if r.snippet else ""),
                        "source": "brave",
                    }
                    for r in results
                ]

            except Exception as e:
                # Fail-open for web search - continue without web results
                logger.warning(f"Web search failed (fail-open): {e}")
                return []

        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                self.web_results = loop.run_until_complete(do_web_search())
            finally:
                loop.close()

            print(f"search.web.completed count={len(self.web_results)}")

        except Exception as e:
            logger.warning(f"Web search error: {e}")
            print(f"search.web.completed count=0 (error: {e})")

        self.timing["web"] = time.time() - start
        self.next(self.ensure_instruct)

    @traced_step
    @step
    def ensure_instruct(self):
        """Phase 4: Restore instruct endpoint with Phase Change coordination.

        Phase Change Pattern: Uses instruct_restore phase change to ensure
        the instruct endpoint is loaded and HEALTHY before synthesis.
        This provides resilient dynamic workload coordination following
        the Ambient workload reliability model.

        Fails fast if instruct endpoint cannot be restored - synthesis
        requires a functioning local LLM endpoint.
        """
        print("search.instruct_restoring")
        start = time.time()

        async def do_ensure_with_phase_change():
            from gaius.client import get_grpc_client

            client = await get_grpc_client()

            # Phase Change: Request instruct restoration via orchestrator
            # Watch OTel progress and await HEALTHY before proceeding
            print("search.instruct.phase_change")
            phase_result = await client.call(
                service="Orchestrator",
                action="phase_change",
                params={
                    "change_type": "instruct_restore",
                    "target_endpoint": "instruct",
                    "await_healthy": True,
                },
                timeout=120.0,
            )

            return phase_result

        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                result = loop.run_until_complete(do_ensure_with_phase_change())
            finally:
                loop.close()

            converged = result.get("converged", False)
            status = result.get("endpoint_status", "unknown")
            duration_ms = result.get("duration_ms", 0)

            if not converged:
                error_msg = result.get("error", "Phase change did not converge")
                raise RuntimeError(
                    f"Instruct phase change failed: {error_msg}\n"
                    f"  Endpoint status: {status}\n"
                    f"  Duration: {duration_ms}ms\n"
                    "  Guru Meditation: #SF.00000015.PHASECHANGE\n"
                    "  Try: /health fix endpoints"
                )

            print(f"search.instruct.phase_change.converged duration_ms={duration_ms}")
            print("search.instruct_ready")

        except Exception as e:
            if "Guru Meditation" in str(e):
                raise
            raise RuntimeError(
                f"Failed to restore instruct endpoint: {e}\n"
                "  Guru Meditation: #SF.00000002.NOINSTRUCT\n"
                "  Try: /health fix instruct"
            ) from e

        self.timing["ensure_instruct"] = time.time() - start

        # BRANCH: Fork to parallel synthesis
        self.next(self.local_synthesis, self.grok_synthesis)

    @traced_step
    @step
    def local_synthesis(self):
        """Phase 5a: Synthesis using local instruct endpoint."""
        print("search.local_synthesis.started")
        start = time.time()

        # Build context from search results
        context = self._build_synthesis_context()

        async def do_synthesis():
            from gaius.client import get_grpc_client

            client = await get_grpc_client()

            prompt = f"""Based on the following search results, provide a comprehensive answer to the query: "{self.query}"

{context}

Provide a clear, well-structured response that synthesizes information from all available sources. Use wikilinks [[like this]] to reference KB documents."""

            result = await client.call(
                service="Scheduler",
                action="complete",
                params={
                    "prompt": prompt,
                    "system_prompt": "You are a research assistant. Synthesize search results into a coherent response. Reference sources using [[wikilinks]] for KB docs and [Markdown links](url) for web sources.",
                    "agent": "instruct",
                    "technique": "cot_reflection",
                    "max_tokens": 2048,
                },
                timeout=120.0,
            )

            return {
                "text": result.get("text", result.get("content", "")),
                "model": result.get("model", "unknown"),
                "latency_ms": int((time.time() - start) * 1000),
            }

        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                self.local_result = loop.run_until_complete(do_synthesis())
            finally:
                loop.close()

            print(f"search.local_synthesis.completed model={self.local_result.get('model', 'unknown')}")

        except Exception as e:
            # Local synthesis failure is fatal - we need at least one synthesis
            logger.error(f"Local synthesis failed: {e}")
            raise RuntimeError(
                f"Local synthesis failed: {e}\n"
                "  Guru Meditation: #SF.00000006.SYNTHFAIL\n"
                "  Try: /health fix instruct"
            ) from e

        self.timing["local_synthesis"] = time.time() - start
        self.next(self.merge_syntheses)

    @traced_step
    @step
    def grok_synthesis(self):
        """Phase 5b: Synthesis using XAI Grok (parallel with local)."""
        if self.skip_grok:
            self.grok_result = None
            print("search.grok_synthesis.skipped (--local mode)")
            self.next(self.merge_syntheses)
            return

        print("search.grok_synthesis.started")
        start = time.time()

        # Build context from search results
        context = self._build_synthesis_context()

        async def do_synthesis():
            from gaius.engine.backends.external.xai_backend import XAIBackend

            backend = XAIBackend(model="grok-4-1-fast")

            if not backend.is_available:
                raise ValueError("XAI_API_KEY not configured")

            prompt = f"""Based on the following search results, provide a comprehensive analysis for the query: "{self.query}"

{context}

Provide a thorough analysis that:
1. Synthesizes information from all sources
2. Highlights key insights
3. Notes any gaps or areas for further research
4. Uses [KB:N] and [Web:N] notation to cite sources"""

            messages = [
                {"role": "system", "content": "You are a research analyst. Provide comprehensive analysis of search results. Cite sources using [KB:N] for knowledge base and [Web:N] for web sources."},
                {"role": "user", "content": prompt},
            ]

            response = await backend.complete(
                messages=messages,
                model="grok-4-1-fast",
                max_tokens=2048,
            )

            return {
                "text": response.content,
                "model": response.model,
                "latency_ms": response.latency_ms,
            }

        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                self.grok_result = loop.run_until_complete(do_synthesis())
            finally:
                loop.close()

            print(f"search.grok_synthesis.completed model={self.grok_result.get('model', 'unknown')}")

        except Exception as e:
            # Grok synthesis failure is non-fatal - continue with local only
            logger.warning(f"Grok synthesis failed (continuing with local): {e}")
            self.grok_result = None
            print(f"search.grok_synthesis.failed (error: {e})")

        self.timing["grok_synthesis"] = time.time() - start
        self.next(self.merge_syntheses)

    @traced_step
    @step
    def merge_syntheses(self, inputs):
        """Phase 6: Join parallel synthesis branches."""
        print("search.synthesis.merging")

        # Manually merge conflicting artifacts from parallel branches
        # Each branch sets its own timing and result fields
        local_timing = {}
        grok_timing = {}
        local_result = None
        grok_result = None

        for inp in inputs:
            # Extract results from each branch
            if hasattr(inp, "local_result") and inp.local_result is not None:
                local_result = inp.local_result
            if hasattr(inp, "grok_result") and inp.grok_result is not None:
                grok_result = inp.grok_result

            # Extract timing from each branch
            if hasattr(inp, "timing"):
                branch_timing = inp.timing or {}
                if "local_synthesis" in branch_timing:
                    local_timing = branch_timing
                if "grok_synthesis" in branch_timing:
                    grok_timing = branch_timing

        # Merge artifacts excluding the conflicting ones
        self.merge_artifacts(inputs, exclude=["next", "timing", "local_result", "grok_result"])  # type: ignore[attr-defined] - metaflow FlowSpec method, lacks stubs

        # Set the combined values
        self.local_result = local_result
        self.grok_result = grok_result

        # Merge timing from both branches - start with base timing from inputs
        merged_timing = {}
        for inp in inputs:
            if hasattr(inp, "timing") and inp.timing:
                merged_timing.update(inp.timing)
        self.timing = merged_timing

        print("search.synthesis.merged")

        # Combined result includes both syntheses
        self.combined = {
            "local": self.local_result,
            "grok": self.grok_result,
        }

        self.next(self.write_kb)

    @traced_step
    @step
    def write_kb(self):
        """Phase 7: Create zettelkasten KB artifact."""
        print("search.kb.writing")

        now = datetime.now()
        date_str = now.strftime("%Y-%m-%d")
        time_str = now.strftime("%H%M%S")
        safe_query = safe_filename(self.query)

        # Generate KB path
        kb_filename = f"{time_str}_search.md"
        self.kb_path = f"scratch/{date_str}/{kb_filename}"

        # Build content
        content = self._build_kb_content(now)

        # Write to KB
        full_path = self.kb_root / self.kb_path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(content)

        print(f"search.kb.written path={self.kb_path}")
        self.next(self.end)

    @traced_step
    @step
    def end(self):
        """Report results and emit lineage."""
        # Calculate totals
        total_time = sum(self.timing.values())
        total_results = len(self.bm25_results) + len(self.vector_results) + len(self.web_results)

        self.emit_event("search.completed", {
            "query": self.query,
            "total_results": total_results,
            "kb_path": self.kb_path,
            "timing": self.timing,
            "correlation_id": self.get_correlation_id(),
        })

        # Emit lineage COMPLETE
        outputs = [Dataset.from_kb(self.kb_path)]
        self.emit_lineage_complete(outputs)

        print("")
        print("=" * 60)
        print("  Search Complete")
        print("=" * 60)
        print(f"  Query:          {self.query}")
        print(f"  BM25 results:   {len(self.bm25_results)}")
        print(f"  Vector results: {len(self.vector_results)}")
        print(f"  Web results:    {len(self.web_results)}")
        print(f"  Local synth:    {'Yes' if self.local_result else 'No'}")
        print(f"  Grok synth:     {'Yes' if self.grok_result else 'Skipped'}")
        print(f"  KB artifact:    {self.kb_path}")
        print(f"  Total time:     {total_time:.1f}s")
        print("=" * 60)

    def _build_synthesis_context(self) -> str:
        """Build context string for synthesis from search results."""
        sections = []

        # KB results (BM25 + Vector combined)
        kb_results = []
        seen_paths = set()

        for i, r in enumerate(self.bm25_results, 1):
            if r["path"] not in seen_paths:
                kb_results.append(f"[KB:{i}] **{r.get('title', r['path'])}**\n{r.get('excerpt', '')}")
                seen_paths.add(r["path"])

        for i, r in enumerate(self.vector_results, len(kb_results) + 1):
            if r["path"] not in seen_paths:
                kb_results.append(f"[KB:{i}] **{r.get('title', r['path'])}**\n{r.get('excerpt', '')}")
                seen_paths.add(r["path"])

        if kb_results:
            sections.append("## Knowledge Base Results\n\n" + "\n\n".join(kb_results))

        # Web results
        if self.web_results:
            web_items = []
            for i, r in enumerate(self.web_results, 1):
                web_items.append(f"[Web:{i}] **{r.get('title', 'Untitled')}**\n{r.get('url', '')}\n{r.get('snippet', '')}")
            sections.append("## Web Search Results\n\n" + "\n\n".join(web_items))

        return "\n\n".join(sections) if sections else "No search results available."

    def _build_kb_content(self, now: datetime) -> str:
        """Build zettelkasten markdown content."""
        sections = []

        # Header
        sections.append(f"# Search: {self.query}\n")
        sections.append("---\n")

        # Grok synthesis (if available) - shown first as primary analysis
        if self.grok_result:
            sections.append("## Grok Analysis\n")
            sections.append(self.grok_result.get("text", ""))
            sections.append(f"\n*Model: {self.grok_result.get('model', 'unknown')} | {self.grok_result.get('latency_ms', 0)}ms*\n")
            sections.append("---\n")

        # Local synthesis (shown if no Grok or as secondary)
        if self.local_result and not self.grok_result:
            sections.append("## Local Analysis\n")
            sections.append(self.local_result.get("text", ""))
            sections.append(f"\n*Model: {self.local_result.get('model', 'unknown')} | {self.local_result.get('latency_ms', 0)}ms*\n")
            sections.append("---\n")

        # KB Sources
        kb_sources = []
        seen_paths = set()

        for r in self.bm25_results + self.vector_results:
            path = r.get("path", "")
            if path and path not in seen_paths:
                title = r.get("title", path)
                excerpt = r.get("excerpt", "")[:80]
                kb_sources.append(f"- [[{path}]] - {title}\n  > {excerpt}...")
                seen_paths.add(path)

        if kb_sources:
            sections.append("## KB Sources\n")
            sections.append("\n".join(kb_sources))
            sections.append("")

        # Web Sources
        if self.web_results:
            sections.append("## Web Sources\n")
            web_sources = []
            for r in self.web_results:
                title = r.get("title", "Untitled")
                url = r.get("url", "")
                web_sources.append(f"- [{title}]({url})")
            sections.append("\n".join(web_sources))
            sections.append("")

        # Actions
        sections.append("## Actions\n")
        sections.append(f"[action:/research {self.query}]")
        sections.append(f"[action:/search --local {self.query}]")
        sections.append("")

        return "\n".join(sections)


if __name__ == "__main__":
    apply_metaflow_config("local")
    SearchFlow()
