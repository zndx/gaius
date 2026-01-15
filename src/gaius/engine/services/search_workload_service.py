"""Search Workload Service - Multi-phase search via Metaflow.

Manages SearchFlow execution via Metaflow Runner API with:
- Progress streaming via stdout parsing
- gRPC SearchFlowEvent emission
- Lineage tracking integration
- GPU orchestration coordination

Guru Meditation Codes:
- #SF.00000001.GPUALLOC: GPU allocation failed for ColNomic
- #SF.00000002.NOINSTRUCT: Instruct endpoint not healthy
- #SF.00000003.BM25UNAVAIL: BM25 not available (missing deps)
- #SF.00000004.QDRANTFAIL: Qdrant connection failed
- #SF.00000005.WEBFAIL: Brave API failed
- #SF.00000006.SYNTHFAIL: Local synthesis failed
- #SF.00000007.FLOWFAIL: Metaflow execution failed
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncIterator

logger = logging.getLogger(__name__)


class SearchError(Exception):
    """Search service error with Guru Meditation code."""

    def __init__(self, message: str, guru_code: str | None = None):
        super().__init__(message)
        self.guru_code = guru_code

    def __str__(self) -> str:
        if self.guru_code:
            return f"{super().__str__()}\n  Guru Meditation: {self.guru_code}"
        return super().__str__()


@dataclass
class SearchConfig:
    """Configuration for Search service."""

    # KB root path for artifacts
    kb_root: str = "build/dev"

    # Default search limits
    default_bm25_limit: int = 10
    default_vector_limit: int = 10
    default_web_limit: int = 5

    # Timeouts (seconds)
    flow_timeout_s: int = 300  # 5 minutes max for full workflow


# Event type mapping to proto enum values
# Matches SearchFlowEvent.Type in gaius_service.proto
_EVENT_TYPES = {
    "queued": 1,
    "bm25_started": 2,
    "bm25_completed": 3,
    "vector_started": 4,
    "vector_evicting": 5,
    "vector_loading": 6,
    "vector_completed": 7,
    "web_started": 8,
    "web_completed": 9,
    "instruct_restoring": 10,
    "instruct_ready": 11,
    "local_synthesis_started": 12,
    "local_synthesis_completed": 13,
    "grok_synthesis_started": 14,
    "grok_synthesis_completed": 15,
    "synthesis_merged": 16,
    "kb_write": 17,
    "completed": 18,
    "failed": 19,
}

# Progress mapping for each event type
_PROGRESS_MAP = {
    "queued": 0.0,
    "bm25_started": 0.05,
    "bm25_completed": 0.15,
    "vector_started": 0.15,
    "vector_evicting": 0.20,
    "vector_loading": 0.30,
    "vector_completed": 0.45,
    "web_started": 0.45,
    "web_completed": 0.50,
    "instruct_restoring": 0.50,
    "instruct_ready": 0.55,
    "local_synthesis_started": 0.60,
    "local_synthesis_completed": 0.75,
    "grok_synthesis_started": 0.60,
    "grok_synthesis_completed": 0.75,
    "grok_synthesis_skipped": 0.60,
    "synthesis_merged": 0.85,
    "kb_write": 0.90,
    "kb_written": 0.95,
    "completed": 1.0,
    "failed": -1.0,
}


class SearchWorkloadService:
    """Search workload service managing Metaflow SearchFlow execution.

    Provides a streaming interface for multi-phase search with:
    - BM25 lexical search
    - ColNomic vector search (GPU orchestrated)
    - Web search (Brave API)
    - Parallel synthesis (local + Grok)
    - KB artifact creation

    Usage:
        service = SearchWorkloadService()
        await service.start()

        async for event in service.run_search(query="flatbuffers"):
            print(f"Progress: {event['progress']:.0%} - {event['message']}")
    """

    def __init__(self, config: SearchConfig | None = None):
        self._config = config or SearchConfig()
        self._running = False

    async def start(self) -> None:
        """Start the search workload service."""
        if self._running:
            return

        logger.info("Starting SearchWorkloadService")
        self._running = True

    async def stop(self) -> None:
        """Stop the search workload service."""
        if not self._running:
            return

        logger.info("Stopping SearchWorkloadService")
        self._running = False

    async def run_search(
        self,
        query: str,
        skip_grok: bool = False,
        bm25_limit: int | None = None,
        vector_limit: int | None = None,
        web_limit: int | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Run multi-phase search via Metaflow SearchFlow.

        Uses Metaflow Runner API for programmatic flow execution with log streaming.
        Progress events are parsed from flow stdout and yielded as dicts.

        Args:
            query: Search query string.
            skip_grok: Skip Grok synthesis (--local mode).
            bm25_limit: BM25 result limit (default: 10).
            vector_limit: Vector search limit (default: 10).
            web_limit: Web search limit (default: 5).

        Yields:
            Progress event dicts with type, progress, message, and optional result.
        """
        from metaflow import Runner

        if not query:
            yield self._make_event("failed", message="Empty query", error="Query is required")
            return

        yield self._make_event("queued", message=f"Starting search for: {query}")

        # Get project root and flow file path
        project_root = Path(__file__).parent.parent.parent.parent.parent
        flow_file = project_root / "src" / "gaius" / "flows" / "search" / "flow.py"

        if not flow_file.exists():
            yield self._make_event(
                "failed",
                message="SearchFlow not found",
                error=f"Flow file missing: {flow_file}",
                guru_code="#SF.00000007.FLOWFAIL",
            )
            return

        # Set environment with KB root
        env = os.environ.copy()
        env["GAIUS_KB_ROOT"] = self._config.kb_root

        try:
            # Use Metaflow Runner API for programmatic execution
            with Runner(
                str(flow_file),
                show_output=False,  # We stream logs ourselves
                env=env,
                cwd=str(project_root),
            ) as runner:
                # Build flow parameters
                flow_params: dict[str, Any] = {
                    "query": query,
                    "skip_grok": skip_grok,
                    "bm25_limit": bm25_limit or self._config.default_bm25_limit,
                    "vector_limit": vector_limit or self._config.default_vector_limit,
                    "web_limit": web_limit or self._config.default_web_limit,
                }

                # Launch flow asynchronously
                executing = await runner.async_run(**flow_params)

                yield self._make_event(
                    "bm25_started",
                    message=f"SearchFlow started (run_id={executing.run.id})",
                )

                # Stream logs and parse progress
                kb_path: str = ""
                async for _, line in executing.stream_log("stdout"):
                    line = line.strip()
                    if not line:
                        continue

                    # Parse flow output for progress events
                    event = self._parse_flow_output(line)
                    if event:
                        # Capture kb_path if present
                        if "path=" in line and "kb." in line:
                            kb_path = line.split("path=")[-1].strip()
                        yield event

                # Wait for completion
                await executing.wait()

                if executing.status == "successful":
                    # If kb_path wasn't captured from stdout, get it from artifacts
                    if not kb_path:
                        try:
                            from metaflow import Flow  # type: ignore[attr-defined] - metaflow lacks type stubs
                            run = Flow("SearchFlow")[executing.run.id]
                            end_task = run["end"].task
                            kb_path = end_task.data.kb_path or ""
                        except Exception as artifact_err:
                            logger.warning(f"Failed to get kb_path from artifacts: {artifact_err}")
                            kb_path = ""

                    yield self._make_event(
                        "completed",
                        message="Search completed",
                        kb_path=kb_path,
                    )
                else:
                    yield self._make_event(
                        "failed",
                        message=f"SearchFlow {executing.status}",
                        guru_code="#SF.00000007.FLOWFAIL",
                    )

        except ImportError:
            yield self._make_event(
                "failed",
                message="Metaflow not found",
                error="Install with: uv add metaflow",
                guru_code="#SF.00000007.FLOWFAIL",
            )
        except Exception as e:
            logger.error(f"SearchFlow failed: {e}")
            yield self._make_event(
                "failed",
                message=f"Flow execution failed: {e}",
                guru_code="#SF.00000007.FLOWFAIL",
            )

    def _parse_flow_output(self, line: str) -> dict[str, Any] | None:
        """Parse flow stdout line and return event dict if recognized.

        Flow outputs progress events in format: search.<phase>.<state> [details]
        Examples:
            search.queued
            search.bm25.started
            search.bm25.completed count=5
            search.vector.evicting
            search.synthesis.merged
            search.kb.written path=scratch/2026-01-14/033350_search.md

        Args:
            line: Output line from flow.

        Returns:
            Event dict or None if line not recognized.
        """
        if not line.startswith("search."):
            # Log non-search output for debugging
            if line and not line.startswith("[") and not line.startswith("="):
                logger.debug(f"Flow output: {line}")
            return None

        # Parse search.* events
        parts = line.split()
        event_key = parts[0].replace("search.", "").replace(".", "_")

        # Extract optional details
        details = {}
        for part in parts[1:]:
            if "=" in part:
                key, value = part.split("=", 1)
                details[key] = value

        # Map to event type
        if event_key in _EVENT_TYPES:
            event = self._make_event(event_key, message=line, **details)
            return event

        # Handle special cases
        if "completed" in event_key:
            base_event = event_key.replace("_completed", "")
            if f"{base_event}_completed" in _EVENT_TYPES:
                return self._make_event(f"{base_event}_completed", message=line, **details)

        if "started" in event_key:
            base_event = event_key.replace("_started", "")
            if f"{base_event}_started" in _EVENT_TYPES:
                return self._make_event(f"{base_event}_started", message=line, **details)

        # Fallback: log unrecognized search events
        logger.debug(f"Unrecognized search event: {line}")
        return None

    def _make_event(
        self,
        event_type: str,
        message: str = "",
        error: str = "",
        guru_code: str = "",
        kb_path: str = "",
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Create a progress event dict.

        Args:
            event_type: Event type key (e.g., "bm25_started").
            message: Human-readable message.
            error: Error message (for failed events).
            guru_code: Guru Meditation code (for failed events).
            kb_path: KB artifact path (for completed events).
            **kwargs: Additional event data.

        Returns:
            Event dict with type, progress, message, timestamp, etc.
        """
        return {
            "type": _EVENT_TYPES.get(event_type, 0),
            "type_name": event_type,
            "progress": _PROGRESS_MAP.get(event_type, 0.0),
            "timestamp_ms": int(time.time() * 1000),
            "message": message,
            "error": error,
            "guru_code": guru_code,
            "kb_path": kb_path,
            **kwargs,
        }
