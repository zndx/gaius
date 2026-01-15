"""Research Workload Service - Multi-pass deep research via Metaflow.

Manages ResearchFlow execution via Metaflow Runner API with:
- Progress streaming via PostgreSQL LISTEN/NOTIFY (research_progress channel)
- gRPC ResearchFlowEvent emission
- MemRL memory retrieval and Q-value updates
- Multi-pass convergence tracking

Architecture:
- Flow writes progress events to meta.research_progress table
- INSERT trigger fires pg_notify('research_progress', <event_json>)
- This service LISTENs on research_progress channel
- Events filtered by session_id and streamed to gRPC client

Guru Meditation Codes:
- #RF.00000001.MEMRETRIEVE: Memory retrieval failed
- #RF.00000002.SWARMFAIL: Swarm agent execution failed
- #RF.00000003.GROKFAIL: XAI API error (non-fatal)
- #RF.00000004.EVALFAIL: Reward computation failed
- #RF.00000005.QUPDATE: Q-value update failed
- #RF.00000006.CONVERGEFAIL: Convergence check failed
- #RF.00000007.FLOWFAIL: Metaflow execution failed
- #RF.00000012.PGLISTENFAIL: PostgreSQL LISTEN failed
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, AsyncIterator

logger = logging.getLogger(__name__)


class ResearchError(Exception):
    """Research service error with Guru Meditation code."""

    def __init__(self, message: str, guru_code: str | None = None):
        super().__init__(message)
        self.guru_code = guru_code

    def __str__(self) -> str:
        if self.guru_code:
            return f"{super().__str__()}\n  Guru Meditation: {self.guru_code}"
        return super().__str__()


@dataclass
class ResearchConfig:
    """Configuration for Research service."""

    # KB root path for artifacts
    kb_root: str = "build/dev"

    # Default research parameters
    default_max_passes: int = 5
    default_drift_threshold: float = 0.15
    default_bm25_limit: int = 10
    default_vector_limit: int = 10
    default_web_limit: int = 5

    # Timeouts (seconds)
    flow_timeout_s: int = 600  # 10 minutes max for full research

    # Database URL for LISTEN/NOTIFY
    database_url: str = "postgres://gaius:gaius@localhost:5438/zndx_gaius?sslmode=disable"


# Event type mapping to proto enum values
# Matches ResearchFlowEvent.Type in gaius_service.proto
_EVENT_TYPES = {
    "queued": 1,
    "memories_retrieving": 2,
    "memories_retrieved": 3,
    "pass_started": 4,
    "pass_search": 5,
    "pass_swarm": 6,
    "pass_grok": 7,
    "pass_evaluate": 8,
    "pass_qupdate": 9,
    "pass_completed": 10,
    "converged": 11,
    "final_synthesis": 12,
    "kb_write": 13,
    "completed": 14,
    "failed": 15,
}

# Progress mapping for each event type (cumulative within pass)
_BASE_PROGRESS = {
    "queued": 0.0,
    "memories_retrieving": 0.02,
    "memories_retrieved": 0.05,
    "converged": 0.85,
    "final_synthesis": 0.90,
    "kb_write": 0.95,
    "completed": 1.0,
    "failed": -1.0,
}


def _compute_pass_progress(pass_num: int, max_passes: int, phase: str) -> float:
    """Compute progress within a research pass.

    Progress is distributed as:
    - 0.00-0.05: Memory retrieval
    - 0.05-0.85: Research passes (distributed across max_passes)
    - 0.85-0.90: Convergence
    - 0.90-0.95: Final synthesis
    - 0.95-1.00: KB write

    Within each pass:
    - started: 0%
    - search: 20%
    - swarm: 50%
    - grok: 70%
    - evaluate: 85%
    - qupdate: 95%
    - completed: 100%
    """
    # Base progress for this pass
    pass_budget = 0.80 / max_passes  # 80% of progress for passes
    pass_base = 0.05 + (pass_num - 1) * pass_budget

    # Phase within pass
    phase_progress = {
        "started": 0.0,
        "search": 0.20,
        "swarm": 0.50,
        "grok": 0.70,
        "evaluate": 0.85,
        "qupdate": 0.95,
        "completed": 1.0,
    }

    return pass_base + pass_budget * phase_progress.get(phase, 0.0)


class ResearchWorkloadService:
    """Research workload service managing Metaflow ResearchFlow execution.

    Provides a streaming interface for multi-pass deep research with:
    - MemRL memory retrieval and Q-value updates
    - 7-agent swarm analysis
    - Grok synthesis
    - Convergence detection
    - KB artifact creation

    Usage:
        service = ResearchWorkloadService()
        await service.start()

        async for event in service.run_research(query="catastrophic forgetting"):
            print(f"Progress: {event['progress']:.0%} - {event['message']}")
    """

    def __init__(self, config: ResearchConfig | None = None):
        self._config = config or ResearchConfig()
        self._running = False

        # Daemon-style state tracking for TUI status/stop support
        self._research_active: bool = False
        self._stop_requested: bool = False
        self._current_query: str = ""
        self._current_pass: int = 0
        self._current_progress: float = 0.0
        self._current_phase: str = ""
        self._start_time: float | None = None
        self._events_count: int = 0

    async def start(self) -> None:
        """Start the research workload service."""
        if self._running:
            return

        logger.info("Starting ResearchWorkloadService")
        self._running = True

    async def stop(self) -> None:
        """Stop the research workload service."""
        if not self._running:
            return

        logger.info("Stopping ResearchWorkloadService")
        self._running = False

    async def get_status(self) -> dict[str, Any]:
        """Return current research state for /research status command.

        Returns:
            Dict with running state, query, pass, progress, phase, elapsed time.
        """
        elapsed_s = 0.0
        if self._start_time is not None:
            elapsed_s = time.time() - self._start_time

        return {
            "running": self._research_active,
            "query": self._current_query,
            "pass": self._current_pass,
            "progress": self._current_progress,
            "phase": self._current_phase,
            "elapsed_s": elapsed_s,
            "events_count": self._events_count,
            "stop_requested": self._stop_requested,
        }

    async def request_stop(self) -> dict[str, Any]:
        """Request graceful stop of current research for /research stop command.

        Returns:
            Dict with success status and message.
        """
        if not self._research_active:
            return {"success": False, "error": "No research running"}

        self._stop_requested = True
        logger.info(f"Stop requested for research query: {self._current_query}")
        return {"success": True, "message": "Stop requested"}

    def _reset_state(self) -> None:
        """Reset daemon state tracking (called at start/end of research)."""
        self._research_active = False
        self._stop_requested = False
        self._current_query = ""
        self._current_pass = 0
        self._current_progress = 0.0
        self._current_phase = ""
        self._start_time = None
        self._events_count = 0

    def _update_state(self, event: dict[str, Any]) -> None:
        """Update daemon state from an event (called on each yield)."""
        self._events_count += 1
        if "progress" in event:
            self._current_progress = event["progress"]
        if "pass_number" in event and event["pass_number"] > 0:
            self._current_pass = event["pass_number"]
        if "type_name" in event:
            self._current_phase = event["type_name"]

    async def run_research(
        self,
        query: str,
        max_passes: int | None = None,
        drift_threshold: float | None = None,
        bm25_limit: int | None = None,
        vector_limit: int | None = None,
        web_limit: int | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Run multi-pass deep research via Metaflow ResearchFlow.

        Uses Metaflow Runner API for programmatic flow execution with
        PostgreSQL LISTEN/NOTIFY for real-time progress streaming.

        Architecture:
        1. Generate session_id before launching flow
        2. Start LISTEN on research_progress channel
        3. Launch ResearchFlow with session_id
        4. Stream pg_notify events matching our session_id
        5. Wait for flow completion

        Args:
            query: Research query string.
            max_passes: Maximum research passes (default: 5).
            drift_threshold: Convergence threshold (default: 0.15).
            bm25_limit: BM25 result limit (default: 10).
            vector_limit: Vector search limit (default: 10).
            web_limit: Web search limit (default: 5).

        Yields:
            Progress event dicts with type, progress, message, and optional result.
        """
        import asyncpg
        from metaflow import Runner

        if not query:
            yield self._make_event("failed", message="Empty query", error="Query is required")
            return

        # Initialize daemon state tracking
        self._reset_state()
        self._research_active = True
        self._current_query = query
        self._start_time = time.time()

        # Generate unique session_id for this research run
        session_id = f"res_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        actual_max_passes = max_passes or self._config.default_max_passes

        event = self._make_event("queued", message=f"Starting research for: {query}")
        self._update_state(event)
        yield event

        # Get project root and flow file path
        project_root = Path(__file__).parent.parent.parent.parent.parent
        flow_file = project_root / "src" / "gaius" / "flows" / "research" / "flow.py"

        if not flow_file.exists():
            yield self._make_event(
                "failed",
                message="ResearchFlow not found",
                error=f"Flow file missing: {flow_file}",
                guru_code="#RF.00000007.FLOWFAIL",
            )
            return

        # Set environment with KB root
        env = os.environ.copy()
        env["GAIUS_KB_ROOT"] = self._config.kb_root
        env["DATABASE_URL"] = self._config.database_url

        # Create asyncio queue for receiving pg_notify events
        event_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        listen_conn: asyncpg.Connection | None = None
        flow_completed = asyncio.Event()

        async def notification_handler(conn: asyncpg.Connection, pid: int, channel: str, payload: str) -> None:
            """Handle pg_notify events from research_progress channel."""
            try:
                event_data = json.loads(payload)
                # Filter by session_id
                if event_data.get("session_id") == session_id:
                    await event_queue.put(event_data)
                    # Check for terminal events
                    if event_data.get("event_name") in ("completed", "failed"):
                        flow_completed.set()
            except json.JSONDecodeError as e:
                logger.warning(f"Failed to parse pg_notify payload: {e}")

        # Start PostgreSQL LISTEN
        try:
            listen_conn = await asyncpg.connect(self._config.database_url)
            await listen_conn.add_listener("research_progress", notification_handler)
            logger.info(f"LISTEN on research_progress for session {session_id}")
        except Exception as e:
            logger.error(f"Failed to setup LISTEN: {e}")
            yield self._make_event(
                "failed",
                message="PostgreSQL LISTEN failed",
                error=str(e),
                guru_code="#RF.00000012.PGLISTENFAIL",
            )
            return

        try:
            # Use Metaflow Runner API for programmatic execution
            with Runner(
                str(flow_file),
                show_output=False,  # Progress comes via pg_notify
                env=env,
                cwd=str(project_root),
            ) as runner:
                # Build flow parameters (including session_id)
                flow_params: dict[str, Any] = {
                    "query": query,
                    "session_id": session_id,  # Pass session_id to flow
                    "max_passes": actual_max_passes,
                    "drift_threshold": drift_threshold or self._config.default_drift_threshold,
                    "bm25_limit": bm25_limit or self._config.default_bm25_limit,
                    "vector_limit": vector_limit or self._config.default_vector_limit,
                    "web_limit": web_limit or self._config.default_web_limit,
                }

                # Launch flow asynchronously
                executing = await runner.async_run(**flow_params)
                logger.info(f"ResearchFlow started: run_id={executing.run.id}")

                # Stream events from queue until flow completes
                kb_path: str = ""
                best_q_value: float = 0.0
                convergence_reason: str = ""
                current_pass: int = 0

                while not flow_completed.is_set():
                    # Check for stop request
                    if self._stop_requested:
                        logger.info("Stop requested, terminating research")
                        event = self._make_event(
                            "failed",
                            message="Research stopped by user",
                            guru_code="#RF.00000008.STOPPED",
                        )
                        self._update_state(event)
                        yield event
                        break

                    try:
                        # Wait for next event with timeout
                        event_data = await asyncio.wait_for(event_queue.get(), timeout=1.0)

                        # Convert pg_notify event to our event format
                        event_name = event_data.get("event_name", "")
                        pass_number = event_data.get("pass_number", 0)
                        progress = event_data.get("progress", 0.0)
                        message = event_data.get("message", "")
                        metadata = event_data.get("metadata", {})

                        if pass_number > 0:
                            current_pass = pass_number

                        # Track results from metadata
                        if "kb_path" in metadata:
                            kb_path = metadata["kb_path"]
                        if "q_value" in metadata:
                            best_q_value = metadata["q_value"]
                        if "reason" in metadata:
                            convergence_reason = metadata["reason"]

                        event = self._make_event(
                            event_name,
                            message=message,
                            pass_number=pass_number,
                            progress_override=progress,
                            kb_path=kb_path,
                            best_q_value=best_q_value,
                            convergence_reason=convergence_reason,
                        )
                        self._update_state(event)
                        yield event

                    except asyncio.TimeoutError:
                        # Check if flow is still running
                        if executing.status not in ("running", "pending"):
                            break
                        continue

                # Drain any remaining events
                while not event_queue.empty():
                    event_data = await event_queue.get()
                    event_name = event_data.get("event_name", "")
                    yield self._make_event(
                        event_name,
                        message=event_data.get("message", ""),
                        pass_number=event_data.get("pass_number", 0),
                        progress_override=event_data.get("progress", 0.0),
                    )

                # Wait for flow completion
                await executing.wait()

                if executing.status == "successful":
                    # Get final results from artifacts if not already captured
                    if not kb_path:
                        try:
                            from metaflow import Flow  # type: ignore[attr-defined]

                            run = Flow("ResearchFlow")[executing.run.id]
                            end_task = run["end"].task
                            kb_path = end_task.data.kb_path or ""
                            best_q_value = max(p["q_value"] for p in end_task.data.passes) if end_task.data.passes else 0.0
                            convergence_reason = end_task.data.convergence_reason or ""
                        except Exception as artifact_err:
                            logger.warning(f"Failed to get results from artifacts: {artifact_err}")

                    yield self._make_event(
                        "completed",
                        message="Research completed",
                        kb_path=kb_path,
                        best_q_value=best_q_value,
                        convergence_reason=convergence_reason,
                        total_passes=current_pass,
                    )
                else:
                    # Extract specific guru code from failed Metaflow task
                    guru_code = "#RF.00000007.FLOWFAIL"
                    error_message = f"ResearchFlow {executing.status}"
                    try:
                        run = Flow("ResearchFlow")[executing.run.id]
                        for step in run.steps():
                            for task in step:
                                if task.exception:
                                    # Extract guru code from exception message
                                    import re

                                    match = re.search(r"#RF\.\d+\.\w+", str(task.exception))
                                    if match:
                                        guru_code = match.group(0)
                                        # Extract the error description (first line after SearchError)
                                        exc_str = str(task.exception)
                                        if "SearchError:" in exc_str:
                                            # Get the error message after "SearchError:"
                                            parts = exc_str.split("SearchError:")
                                            if len(parts) > 1:
                                                first_line = parts[1].split("\n")[0].strip()
                                                error_message = first_line
                                        break
                            if guru_code != "#RF.00000007.FLOWFAIL":
                                break
                    except Exception as extract_err:
                        logger.warning(f"Failed to extract guru code: {extract_err}")

                    yield self._make_event(
                        "failed",
                        message=error_message,
                        guru_code=guru_code,
                    )

        except ImportError:
            yield self._make_event(
                "failed",
                message="Metaflow not found",
                error="Install with: uv add metaflow",
                guru_code="#RF.00000007.FLOWFAIL",
            )
        except Exception as e:
            logger.error(f"ResearchFlow failed: {e}")
            yield self._make_event(
                "failed",
                message=f"Flow execution failed: {e}",
                guru_code="#RF.00000007.FLOWFAIL",
            )
        finally:
            # Reset daemon state
            self._research_active = False

            # Cleanup LISTEN connection
            if listen_conn:
                try:
                    await listen_conn.remove_listener("research_progress", notification_handler)
                    await listen_conn.close()
                    logger.info(f"Closed LISTEN connection for session {session_id}")
                except Exception as e:
                    logger.warning(f"Error closing LISTEN connection: {e}")

    def _parse_flow_output(
        self,
        line: str,
        current_pass: int,
        max_passes: int,
    ) -> dict[str, Any] | None:
        """Parse flow stdout line and return event dict if recognized.

        Flow outputs progress events in format: research.<phase>.<state> [details]
        Examples:
            research.queued
            research.memories.retrieving
            research.memories.retrieved count=3
            research.pass.1.started
            research.pass.1.search type=bm25
            research.pass.1.swarm
            research.pass.1.grok
            research.pass.1.evaluate.completed coherence=0.85 coverage=0.78 novelty=0.45
            research.pass.1.qupdate.completed q_value=0.72
            research.converged reason=drift_converged:0.12
            research.synthesis.final
            research.kb.written path=scratch/2026-01-14/143022_research.md

        Args:
            line: Output line from flow.
            current_pass: Current pass number.
            max_passes: Maximum passes.

        Returns:
            Event dict or None if line not recognized.
        """
        if not line.startswith("research."):
            # Log non-research output for debugging
            if line and not line.startswith("[") and not line.startswith("="):
                logger.debug(f"Flow output: {line}")
            return None

        # Parse research.* events
        parts = line.split()
        event_path = parts[0].replace("research.", "")

        # Extract optional details
        details = {}
        for part in parts[1:]:
            if "=" in part:
                key, value = part.split("=", 1)
                details[key] = value

        # Parse pass events: research.pass.N.phase
        if event_path.startswith("pass."):
            path_parts = event_path.split(".")
            if len(path_parts) >= 3:
                try:
                    pass_num = int(path_parts[1])
                    phase = path_parts[2]

                    # Calculate progress
                    progress = _compute_pass_progress(pass_num, max_passes, phase)

                    return self._make_event(
                        f"pass_{phase}",
                        message=line,
                        pass_number=pass_num,
                        progress_override=progress,
                        **details,
                    )
                except (ValueError, IndexError):
                    pass

        # Map common events
        event_mapping = {
            "queued": "queued",
            "memories.retrieving": "memories_retrieving",
            "memories.retrieved": "memories_retrieved",
            "converged": "converged",
            "synthesis.final": "final_synthesis",
            "kb.writing": "kb_write",
            "kb.written": "completed",
        }

        for pattern, event_type in event_mapping.items():
            if event_path == pattern or event_path.startswith(pattern):
                return self._make_event(event_type, message=line, **details)

        # Fallback: log unrecognized research events
        logger.debug(f"Unrecognized research event: {line}")
        return None

    def _make_event(
        self,
        event_type: str,
        message: str = "",
        error: str = "",
        guru_code: str = "",
        kb_path: str = "",
        pass_number: int = 0,
        progress_override: float | None = None,
        best_q_value: float = 0.0,
        convergence_reason: str = "",
        total_passes: int = 0,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Create a progress event dict.

        Args:
            event_type: Event type key (e.g., "pass_started").
            message: Human-readable message.
            error: Error message (for failed events).
            guru_code: Guru Meditation code (for failed events).
            kb_path: KB artifact path (for completed events).
            pass_number: Current pass number.
            progress_override: Override calculated progress.
            best_q_value: Best Q-value achieved.
            convergence_reason: Why research converged.
            total_passes: Total passes completed.
            **kwargs: Additional event data.

        Returns:
            Event dict with type, progress, message, timestamp, etc.
        """
        # Determine progress
        if progress_override is not None:
            progress = progress_override
        elif event_type in _BASE_PROGRESS:
            progress = _BASE_PROGRESS[event_type]
        else:
            progress = 0.0

        return {
            "type": _EVENT_TYPES.get(event_type.split("_")[0], 0),
            "type_name": event_type,
            "progress": progress,
            "timestamp_ms": int(time.time() * 1000),
            "message": message,
            "error": error,
            "guru_code": guru_code,
            "kb_path": kb_path,
            "pass_number": pass_number,
            "best_q_value": best_q_value,
            "convergence_reason": convergence_reason,
            "total_passes": total_passes,
            **kwargs,
        }
