"""PostgreSQL progress events for ArticleCurationFlow.

Writes progress events to meta.article_curation_progress table which triggers
pg_notify for real-time TUI updates.

Step types for article curation:
- start: Flow started
- select: Article selected
- research: Zettelkasten synthesis
- acquire: External source acquisition
- summarize: LLM summarization
- draft: Draft generation
- base: .base file creation
- cards: Card creation
- complete: Flow completed
- failed: Flow failed
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)

# Step definitions with progress values
STEPS = {
    "start": {"number": 1, "progress": 0.0},
    "select": {"number": 2, "progress": 0.10},
    "research": {"number": 3, "progress": 0.20},
    "acquire": {"number": 4, "progress": 0.35},
    "summarize": {"number": 5, "progress": 0.50},
    "draft": {"number": 6, "progress": 0.65},
    "base": {"number": 7, "progress": 0.80},
    "cards": {"number": 8, "progress": 0.85},
    "publish": {"number": 9, "progress": 0.95},
    "complete": {"number": 10, "progress": 1.0},
    "failed": {"number": -1, "progress": -1.0},
}

TOTAL_STEPS = 10


def generate_run_id() -> str:
    """Generate a unique run ID for article curation."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"acf_{timestamp}"


def emit_progress(
    run_id: str,
    step: str,
    message: str = "",
    metadata: dict[str, Any] | None = None,
) -> None:
    """Emit progress event to PostgreSQL with pg_notify.

    Uses psycopg2 synchronously since Metaflow steps run in separate processes.

    Args:
        run_id: Flow run ID (e.g., acf_20260202_050000)
        step: Step name (start, select, research, acquire, etc.)
        message: Human-readable message for TUI display
        metadata: Optional additional data (slug, sources_count, etc.)
    """
    import psycopg2

    step_info = STEPS.get(step, {"number": 0, "progress": 0.0})
    step_number = step_info["number"]
    progress = step_info["progress"]
    metadata = metadata or {}

    # Get database URL
    from gaius.core.config import get_database_url
    db_url = get_database_url()

    try:
        conn = psycopg2.connect(db_url)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO meta.article_curation_progress
                    (run_id, step, step_number, total_steps, progress, message, metadata)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        run_id,
                        step,
                        step_number,
                        TOTAL_STEPS,
                        progress,
                        message,
                        json.dumps(metadata),
                    ),
                )
                conn.commit()
                logger.debug(f"Emitted progress: {step} ({progress:.0%}) - {message}")
        finally:
            conn.close()
    except Exception as e:
        # Don't fail the flow on progress emission errors
        logger.warning(f"Failed to emit progress event: {e}")


def emit_start(run_id: str, slug: str | None = None) -> None:
    """Emit flow start event."""
    emit_progress(
        run_id,
        "start",
        f"Starting article curation{f' for {slug}' if slug else ''}...",
        {"slug": slug} if slug else {},
    )


def emit_select(run_id: str, slug: str, title: str) -> None:
    """Emit article selection event."""
    emit_progress(
        run_id,
        "select",
        f"Selected: {title}",
        {"slug": slug, "title": title},
    )


def emit_research(run_id: str, zk_count: int) -> None:
    """Emit research synthesis event."""
    emit_progress(
        run_id,
        "research",
        f"Synthesizing {zk_count} zettelkasten notes...",
        {"zk_count": zk_count},
    )


def emit_acquire(run_id: str, sources_count: int) -> None:
    """Emit source acquisition event."""
    emit_progress(
        run_id,
        "acquire",
        f"Acquired {sources_count} external sources",
        {"sources_count": sources_count},
    )


def emit_summarize(run_id: str, sources_count: int) -> None:
    """Emit summarization event."""
    emit_progress(
        run_id,
        "summarize",
        f"Summarizing {sources_count} sources...",
        {"sources_count": sources_count},
    )


def emit_draft(run_id: str, word_count: int) -> None:
    """Emit draft generation event."""
    emit_progress(
        run_id,
        "draft",
        f"Generated draft ({word_count} words)",
        {"word_count": word_count},
    )


def emit_base(run_id: str, base_path: str, ref_count: int) -> None:
    """Emit .base file creation event."""
    emit_progress(
        run_id,
        "base",
        f"Created .base file with {ref_count} references",
        {"base_path": base_path, "ref_count": ref_count},
    )


def emit_cards(run_id: str, cards_count: int) -> None:
    """Emit card creation event."""
    emit_progress(
        run_id,
        "cards",
        f"Created {cards_count} cards (pending)",
        {"cards_count": cards_count},
    )


def emit_publish(run_id: str, published_count: int) -> None:
    """Emit card publish event."""
    emit_progress(
        run_id,
        "publish",
        f"Published {published_count} cards and synced KV",
        {"published_count": published_count},
    )


def emit_complete(
    run_id: str,
    slug: str,
    sources_count: int,
    cards_count: int,
) -> None:
    """Emit flow completion event."""
    emit_progress(
        run_id,
        "complete",
        f"Completed: {cards_count} cards from {sources_count} sources",
        {
            "slug": slug,
            "sources_count": sources_count,
            "cards_count": cards_count,
        },
    )


def emit_failed(run_id: str, error: str) -> None:
    """Emit flow failure event."""
    emit_progress(
        run_id,
        "failed",
        f"Failed: {error}",
        {"error": error},
    )
