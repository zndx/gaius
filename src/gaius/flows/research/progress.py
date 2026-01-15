"""PostgreSQL progress events for ResearchFlow.

Writes progress events to meta.research_progress table which triggers
pg_notify for real-time TUI updates. Replaces unreliable stdout parsing.

Event types match ResearchFlowEvent.Type proto enum for consistency.

OTel Integration:
    Progress events are also emitted to OTel spans for end-to-end observability.
    This enables NiFi-side filtering by event_name for per-step processors.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

# Event type enum values (matching ResearchFlowEvent.Type proto)
EVENT_TYPES = {
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

# Progress values for each event type (cumulative)
BASE_PROGRESS = {
    "queued": 0.0,
    "memories_retrieving": 0.02,
    "memories_retrieved": 0.05,
    "pass_started": 0.10,
    "pass_search": 0.20,
    "pass_swarm": 0.40,
    "pass_grok": 0.60,
    "pass_evaluate": 0.70,
    "pass_qupdate": 0.75,
    "pass_completed": 0.80,
    "converged": 0.85,
    "final_synthesis": 0.90,
    "kb_write": 0.95,
    "completed": 1.0,
    "failed": -1.0,
}


def compute_progress(event_name: str, pass_number: int, max_passes: int) -> float:
    """Compute progress value accounting for pass number.

    Progress is distributed as:
    - 0.00-0.05: Memory retrieval
    - 0.05-0.85: Research passes (distributed across max_passes)
    - 0.85-0.90: Convergence
    - 0.90-0.95: Final synthesis
    - 0.95-1.00: KB write

    Args:
        event_name: Event type name
        pass_number: Current pass number (1-indexed)
        max_passes: Maximum passes allowed

    Returns:
        Progress value 0.0-1.0
    """
    # Pre-pass events
    if event_name in ("queued", "memories_retrieving", "memories_retrieved"):
        return BASE_PROGRESS.get(event_name, 0.0)

    # Post-pass events
    if event_name in ("converged", "final_synthesis", "kb_write", "completed", "failed"):
        return BASE_PROGRESS.get(event_name, 0.0)

    # Pass events: distribute 0.05-0.85 across passes
    if pass_number <= 0:
        pass_number = 1

    pass_budget = 0.80 / max_passes
    pass_base = 0.05 + (pass_number - 1) * pass_budget

    # Phase within pass
    phase_offsets = {
        "pass_started": 0.0,
        "pass_search": 0.20,
        "pass_swarm": 0.40,
        "pass_grok": 0.60,
        "pass_evaluate": 0.75,
        "pass_qupdate": 0.85,
        "pass_completed": 1.0,
    }

    offset = phase_offsets.get(event_name, 0.0)
    return min(0.85, pass_base + pass_budget * offset)


def _emit_otel_progress(
    event_name: str,
    progress: float,
    session_id: str,
    pass_number: int,
    message: str,
) -> None:
    """Emit progress event to current OTel span.

    Bridges PostgreSQL progress events to OTel for end-to-end observability.
    This enables NiFi ListenOTLP to receive progress events and route them
    to per-step processors based on event_name.

    Args:
        event_name: Event type name (pass_search, completed, etc.)
        progress: Progress value 0.0-1.0
        session_id: Research session ID for correlation
        pass_number: Current pass number
        message: Human-readable message
    """
    try:
        from opentelemetry import trace

        span = trace.get_current_span()
        if span is None or not hasattr(span, "add_event"):
            logger.debug("No active OTel span for progress emission")
            return

        # Build attributes with meaningful observability value
        attrs: dict[str, Any] = {
            "progress.pct": round(progress * 100, 1),
            "progress.phase": event_name,
            "progress.session_id": session_id,
        }

        if pass_number > 0:
            attrs["progress.pass_number"] = pass_number

        if message:
            attrs["progress.message"] = message

        # Include research-specific attributes for NiFi filtering
        attrs["research.event_name"] = event_name
        attrs["research.session_id"] = session_id

        span.add_event("progress", attrs)
        logger.debug(f"Emitted OTel progress: {event_name} ({progress:.0%})")

    except ImportError:
        # OTel not available - log but don't fail
        logger.debug("OpenTelemetry not available for progress emission")
    except Exception as e:
        # Log error but don't fail the flow on OTel emission errors
        logger.warning(f"Failed to emit OTel progress event: {e}")


def emit_progress(
    session_id: str,
    event_name: str,
    pass_number: int = 0,
    max_passes: int = 5,
    message: str = "",
    metadata: dict[str, Any] | None = None,
) -> None:
    """Emit progress event to PostgreSQL and OTel.

    This triggers pg_notify('research_progress', ...) for real-time TUI updates
    AND emits an OTel span event for NiFi visibility.

    Uses psycopg2 synchronously since Metaflow steps run in separate processes.

    Args:
        session_id: Research session ID (e.g., res_20260114_070504)
        event_name: Event type name (queued, pass_search, completed, etc.)
        pass_number: Current pass number (1-indexed, 0 for non-pass events)
        max_passes: Maximum passes for progress calculation
        message: Human-readable message for TUI display
        metadata: Optional additional data (q_value, sources_count, etc.)
    """
    import psycopg2

    event_type = EVENT_TYPES.get(event_name, 0)
    progress = compute_progress(event_name, pass_number, max_passes)
    metadata = metadata or {}

    # Emit to OTel span (for NiFi visibility)
    _emit_otel_progress(event_name, progress, session_id, pass_number, message)

    # Emit to PostgreSQL (for TUI LISTEN/NOTIFY)
    db_url = os.environ.get("DATABASE_URL", "postgres://gaius:gaius@localhost:5432/gaius")

    try:
        conn = psycopg2.connect(db_url)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO meta.research_progress
                    (session_id, event_type, event_name, pass_number, progress, message, metadata)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        session_id,
                        event_type,
                        event_name,
                        pass_number,
                        progress,
                        message,
                        json.dumps(metadata),
                    ),
                )
                conn.commit()
                logger.debug(f"Emitted PostgreSQL progress: {event_name} ({progress:.0%}) - {message}")
        finally:
            conn.close()
    except Exception as e:
        # Don't fail the flow on progress emission errors
        logger.warning(f"Failed to emit PostgreSQL progress event: {e}")
