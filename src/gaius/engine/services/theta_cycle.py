"""Drain the current Theta consolidation slice (NVAR → BERTSubs → KG).

Stale ``scheduled`` rows (empty Qdrant latent era) are superseded. The live
input is ``cognition_thoughts`` for the ISO week. Engine-First: the caller
passes the engine's ThetaService consolidator.

Guru:
- #THETA.00000005.CONSFAIL
- #THETA.00000008.STALESLICE
- #THETA.00000009.NOTHOUGHTS
- #THETA.00000010.NOENCODE
"""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from gaius.agents.theta.consolidation import get_week_slice_id

logger = logging.getLogger(__name__)

GURU = "#THETA.00000005.CONSFAIL"
STALE = "#THETA.00000008.STALESLICE"
NOTHOUGHTS = "#THETA.00000009.NOTHOUGHTS"
NOENCODE = "#THETA.00000010.NOENCODE"

STALE_REASON = (
    f"{STALE} Qdrant latent store empty; superseded 2026-09-15; "
    "consolidation input is cognition_thoughts"
)

Consolidator = Callable[[str], Awaitable[dict[str, Any]]]


async def supersede_stale(conn: Any, current_slice: str) -> int:
    """Fail every scheduled row that is not this week's slice."""
    return int(
        await conn.fetchval(
            """
            WITH u AS (
                UPDATE theta_consolidation_runs
                   SET status = 'failed',
                       completed_at = NOW(),
                       error = $2
                 WHERE status = 'scheduled'
                   AND slice_id <> $1
             RETURNING id
            )
            SELECT count(*)::int FROM u
            """,
            current_slice,
            STALE_REASON,
        )
        or 0
    )


async def consume_pending(
    conn: Any,
    *,
    consolidator: Consolidator,
    current_slice: str | None = None,
    max_jobs: int = 1,
) -> list[dict[str, Any]]:
    """Run at most the current ISO-week slice. Never drain the stale backlog."""
    slice_id = current_slice or get_week_slice_id()
    superseded = await supersede_stale(conn, slice_id)
    rows = await conn.fetch("SELECT * FROM get_pending_theta_consolidations()")
    rows = [r for r in rows if str(r["slice_id"]) == slice_id]
    if not rows:
        job_id = await conn.fetchval("SELECT schedule_theta_consolidation($1)", slice_id)
        if job_id:
            rows = await conn.fetch("SELECT * FROM get_pending_theta_consolidations()")
            rows = [r for r in rows if str(r["slice_id"]) == slice_id]
    out: list[dict[str, Any]] = [{"superseded": superseded, "slice_id": slice_id}]
    for row in rows[:max_jobs]:
        job_id = int(row["job_id"])
        started = await conn.fetchval("SELECT start_theta_consolidation($1)", job_id)
        if not started:
            out.append({"job_id": job_id, "slice_id": slice_id, "skipped": True})
            continue
        try:
            result = await consolidator(slice_id)
        except Exception as e:
            logger.exception("%s consolidation %s", GURU, slice_id)
            result = {"success": False, "error": str(e), "guru_code": GURU}
        guru = str(result.get("guru_code") or "")
        err = None if result.get("success") else (result.get("error") or guru or GURU)
        signal = result.get("signal") or {}
        await conn.fetchval(
            "SELECT complete_theta_consolidation($1,$2,$3,$4,$5,$6,$7)",
            job_id,
            signal.get("urgency"),
            signal.get("drift"),
            int(result.get("candidates_evaluated") or 0),
            int(result.get("candidates_selected") or 0),
            int(result.get("documents_augmented") or 0),
            err,
        )
        out.append(
            {
                "job_id": job_id,
                "slice_id": slice_id,
                "success": bool(result.get("success")),
                "error": err,
                "guru_code": guru,
                "candidates_evaluated": int(result.get("candidates_evaluated") or 0),
                "candidates_selected": int(result.get("candidates_selected") or 0),
                "documents_augmented": int(result.get("documents_augmented") or 0),
                "effectiveness": result.get("effectiveness"),
            }
        )
    return out
