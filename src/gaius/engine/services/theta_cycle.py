"""Consume pending Theta consolidation jobs (NVAR → BERTSubs → KG).

pg_cron ``theta-weekly-consolidation`` only INSERTs ``scheduled`` rows.
This module is the missing consumer: start → ThetaAgent.run_consolidation
→ complete. THS settle/expire is Signals ``tier_settle`` / DataProductTierUpkeep,
not this cycle.

Guru: #THETA.00000005.CONSFAIL
"""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

logger = logging.getLogger(__name__)

GURU = "#THETA.00000005.CONSFAIL"

Consolidator = Callable[[str], Awaitable[dict[str, Any]]]


async def consume_pending(
    conn: Any,
    *,
    consolidator: Consolidator,
    max_jobs: int = 10,
    schedule_if_empty: bool = True,
) -> list[dict[str, Any]]:
    """Drain ``get_pending_theta_consolidations()``. Returns per-job reports."""
    rows = await conn.fetch("SELECT * FROM get_pending_theta_consolidations()")
    if not rows and schedule_if_empty:
        job_id = await conn.fetchval("SELECT schedule_theta_consolidation(NULL)")
        if job_id:
            rows = await conn.fetch("SELECT * FROM get_pending_theta_consolidations()")
    out: list[dict[str, Any]] = []
    for row in rows[: max_jobs]:
        job_id = int(row["job_id"])
        slice_id = str(row["slice_id"])
        started = await conn.fetchval("SELECT start_theta_consolidation($1)", job_id)
        if not started:
            out.append({"job_id": job_id, "slice_id": slice_id, "skipped": True})
            continue
        try:
            result = await consolidator(slice_id)
        except Exception as e:
            logger.exception("%s consolidation %s", GURU, slice_id)
            result = {"success": False, "error": str(e), "guru_code": GURU}
        signal = result.get("signal") or {}
        err = None if result.get("success") else (result.get("error") or GURU)
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
                "candidates_evaluated": int(result.get("candidates_evaluated") or 0),
                "candidates_selected": int(result.get("candidates_selected") or 0),
                "documents_augmented": int(result.get("documents_augmented") or 0),
            }
        )
    return out


async def engine_consolidator(slice_id: str) -> dict[str, Any]:
    """Run the in-process ThetaAgent (same path as gRPC run_consolidation)."""
    from gaius.engine.services.theta_service import ThetaConfig, ThetaService

    svc = ThetaService(ThetaConfig())
    return await svc.run_consolidation(temporal_slice=slice_id)
