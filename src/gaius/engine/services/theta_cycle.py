"""Queue helpers for ThetaCycleFlow (Metaflow). The engine owns the table.

Stale ``scheduled`` rows are superseded. Live input is ``cognition_thoughts``.
Encoding is EmbedTexts on the engine; BERTSubs runs in the flow process.

Guru:
- #THETA.00000008.STALESLICE
- #THETA.00000009.NOTHOUGHTS
- #THETA.00000010.NOENCODE
- #THETA.00000011.NOPAIRS
- #THETA.00000012.THINCABI
- #THETA.00000013.CONSFAIL
"""

from __future__ import annotations

import logging
import json
from typing import Any

from gaius.agents.theta.consolidation import get_previous_week_slice_id

logger = logging.getLogger(__name__)

GURU = "#THETA.00000013.CONSFAIL"
STALE = "#THETA.00000008.STALESLICE"
NOTHOUGHTS = "#THETA.00000009.NOTHOUGHTS"
NOENCODE = "#THETA.00000010.NOENCODE"
NOPAIRS = "#THETA.00000011.NOPAIRS"

STALE_REASON = (
    f"{STALE} Qdrant latent store empty; superseded 2026-09-15; "
    "consolidation input is cognition_thoughts"
)

async def enqueue_theta_cycle(
    conn: Any,
    *,
    slice_id: str = "",
    source: str = "operator",
) -> tuple[int, bool]:
    """Insert ``theta_cycle`` for ThetaCycleFlow. Does not run BERTSubs.

    Returns (scheduled_tasks.id, freshly_queued). A pending row is reused.
    """
    existing = await conn.fetchval(
        """
        SELECT id FROM scheduled_tasks
         WHERE task_type = 'theta_cycle' AND completed_at IS NULL
         ORDER BY id LIMIT 1
        """
    )
    if existing is not None:
        return int(existing), False
    payload: dict[str, str] = {}
    if slice_id:
        payload["slice_id"] = slice_id
    tid = await conn.fetchval(
        """
        INSERT INTO scheduled_tasks (task_type, payload, source, scheduled_for)
        VALUES ('theta_cycle', $1::jsonb, $2, NOW())
        RETURNING id
        """,
        json.dumps(payload),
        source,
    )
    return int(tid), True


async def supersede_stale(conn: Any, current_slice: str) -> int:
    """Fail every scheduled row that is not this week's slice."""
    return int(
        await conn.fetchval(
            """
            WITH u AS (
                UPDATE theta_consolidation_runs
                   SET status = 'superseded',
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


async def load_thoughts(conn: Any, slice_id: str) -> list[dict[str, Any]]:
    rows = await conn.fetch(
        """
        SELECT id::text AS id, title, content, domains, kb_paths
          FROM cognition_thoughts
         WHERE to_char(created_at AT TIME ZONE 'UTC', 'IYYY')
               || '-W' || to_char(created_at AT TIME ZONE 'UTC', 'IW')
               = $1
        """,
        slice_id,
    )
    return [dict(r) for r in rows]


async def start_current_job(conn: Any, slice_id: str) -> tuple[int | None, int]:
    superseded = await supersede_stale(conn, slice_id)
    rows = await conn.fetch("SELECT * FROM get_pending_theta_consolidations()")
    rows = [r for r in rows if str(r["slice_id"]) == slice_id]
    if not rows:
        job_id = await conn.fetchval("SELECT schedule_theta_consolidation($1)", slice_id)
        if job_id:
            rows = [{"job_id": job_id, "slice_id": slice_id}]
    if not rows:
        return None, superseded
    job_id = int(rows[0]["job_id"])
    started = await conn.fetchval("SELECT start_theta_consolidation($1)", job_id)
    if not started:
        return None, superseded
    return job_id, superseded


async def complete_job(dsn: str, job_id: int, result: dict[str, Any]) -> None:
    import asyncpg

    signal = result.get("signal") or {}
    err = None if result.get("success") else (result.get("error") or result.get("guru_code") or GURU)
    pool = await asyncpg.create_pool(dsn)
    try:
        async with pool.acquire() as conn:
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
    finally:
        await pool.close()


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Engine EmbedTexts RPC (ColBERT-Zero 128-d agg). Raises on empty/transport failure."""
    import grpc

    from gaius.engine.generated import EmbedTextsRequest
    from gaius.engine.generated.gaius_service_pb2_grpc import GaiusServiceStub
    from gaius.flows.lattice import engine_target

    if not texts:
        return []
    channel = grpc.insecure_channel(engine_target())
    try:
        stub = GaiusServiceStub(channel)
        resp = stub.EmbedTexts(EmbedTextsRequest(texts=texts), timeout=180.0)
    finally:
        channel.close()
    vecs = [list(v.values) for v in resp.embeddings]
    if not vecs:
        raise RuntimeError("#THETA.00000010.NOENCODE empty EmbedTexts")
    return vecs

