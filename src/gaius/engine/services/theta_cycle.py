"""Queue helpers for ThetaCycleFlow (Metaflow). The engine owns the table.

Stale ``scheduled`` rows are superseded. Live input is ``cognition_thoughts``.
The Metaflow child owns ColBERT-Zero (LIGHT) and BERTSubs; the engine owns the queue.

Guru:
- #THETA.00000008.STALESLICE
- #THETA.00000009.NOTHOUGHTS
- #THETA.00000010.NOENCODE
- #THETA.00000011.NOPAIRS
- #THETA.00000012.THINCABI
- #THETA.00000013.CONSFAIL
- #THETA.00000014.NOUNDERSTANDING
"""

from __future__ import annotations

import logging
import json
from typing import Any

from gaius.agents.theta.consolidation import get_previous_week_slice_id, get_week_slice_id

logger = logging.getLogger(__name__)

GURU = "#THETA.00000013.CONSFAIL"
STALE = "#THETA.00000008.STALESLICE"
NOTHOUGHTS = "#THETA.00000009.NOTHOUGHTS"
NOENCODE = "#THETA.00000010.NOENCODE"
NOPAIRS = "#THETA.00000011.NOPAIRS"
NOUNDERSTANDING = "#THETA.00000014.NOUNDERSTANDING"

# Matches coord_lease postures — not hold-uptime keys.
LOGICAL_DATE_POSTURE = "zndx.logical_date"
WINDOW_DATE_POSTURE = "zndx.window_date"


def _as_datetime(value: Any):
    from datetime import datetime, timezone

    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def as_meta_dict(value: Any) -> dict[str, Any]:
    """JSONB/JSON/str metadata → dict. ``dict("…")`` raises ValueError."""
    if value is None or value == "":
        return {}
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return {}
    if isinstance(value, dict):
        return dict(value)
    return {}


def utc_day(value: Any) -> str:
    """UTC calendar day YYYY-MM-DD, or empty."""
    from datetime import timezone

    dt = _as_datetime(value)
    if dt is None:
        raw = str(value or "").strip()
        return raw[:10] if len(raw) >= 10 and raw[4] == "-" else ""
    return dt.astimezone(timezone.utc).date().isoformat()


def iso_week_days(slice_id: str) -> list[str]:
    """Monday–Sunday UTC dates that constitute an ISO week artifact."""
    from datetime import datetime, timedelta

    try:
        year_s, week_s = slice_id.split("-W", 1)
        monday = datetime.fromisocalendar(int(year_s), int(week_s), 1).date()
    except (TypeError, ValueError):
        return []
    return [(monday + timedelta(days=i)).isoformat() for i in range(7)]


def week_is_complete(windows: list[str], slice_id: str) -> bool:
    need = set(iso_week_days(slice_id))
    return bool(need) and need <= {str(w)[:10] for w in windows}


# Coverage of the seven days is not a result. Both counters at zero means
# infer never recorded what it did.
BLANK_RESULT = (
    "#THETA.00000013.CONSFAIL coverage without an infer result "
    "(candidates_evaluated=0 and documents_augmented=0)"
)


def result_is_blank(evaluated: int, augmented: int) -> bool:
    return int(evaluated or 0) == 0 and int(augmented or 0) == 0


def run_closes_week(window: str, windows: list[str], slice_id: str) -> bool:
    """Monday (no window) closes the week. A day closes it only as the seventh."""
    if not slice_id:
        return False
    day = str(window or "")[:10]
    if not day:
        return True
    have = [str(w)[:10] for w in windows]
    if day not in have:
        have.append(day)
    return week_is_complete(have, slice_id)


def completion_status(
    *,
    success: bool,
    windows_done: bool,
    has_window: bool,
    total_evaluated: int,
    total_augmented: int,
    err: str | None,
    has_understanding: bool = False,
) -> tuple[str, str | None]:
    """Ledger status for this increment.

    A day that did not finish the week stays ``scheduled``. A finished week
    is completed only when a consolidation thought was written for the
    cognition loop. Pair counters are not that understanding: both at zero
    is still ``CONSFAIL``, and a non-zero count without the thought is
    ``NOUNDERSTANDING``.
    """
    if not success:
        if has_window:
            return "scheduled", err
        return "failed", err
    if has_window and not windows_done:
        return "scheduled", None
    if has_understanding:
        return "completed", None
    if result_is_blank(total_evaluated, total_augmented):
        return "failed", BLANK_RESULT
    return "failed", (
        f"{NOUNDERSTANDING} infer counters were recorded but the week "
        "was not written back to the cognition loop"
    )


def merge_centroid(
    prior: list[float] | None, prior_n: int, new_vecs: list[Any]
) -> tuple[list[float], int]:
    """Running mean of thought vectors — the week centroid, not a day product."""
    import numpy as np

    n0 = int(prior_n or 0)
    if not new_vecs:
        return list(prior or []), n0
    arr = np.asarray(new_vecs, dtype=float)
    if arr.size == 0:
        return list(prior or []), n0
    total = arr.sum(axis=0)
    n = n0 + int(arr.shape[0])
    if prior and n0:
        total = total + np.asarray(prior, dtype=float) * n0
    return (total / n).tolist(), n


def slice_id_for_logical_date(logical_date: Any) -> str:
    """Monday 06:00 on-time tick: the ISO week that closed relative to that Monday."""
    dt = _as_datetime(logical_date)
    if dt is None:
        return ""
    return get_previous_week_slice_id(dt)


def window_date_from_activity(a: dict[str, Any] | None) -> str:
    raw = str(((a or {}).get("postures") or {}).get(WINDOW_DATE_POSTURE) or "").strip()
    return utc_day(raw) if raw else ""


def slice_id_from_activity(a: dict[str, Any] | None) -> str:
    """Week *artifact* id: containing week for a daily window, else previous week of the Monday tick."""
    wd = window_date_from_activity(a)
    if wd:
        dt = _as_datetime(wd + "T00:00:00+00:00")
        return get_week_slice_id(dt) if dt else ""
    iso = str(((a or {}).get("postures") or {}).get(LOGICAL_DATE_POSTURE) or "").strip()
    return slice_id_for_logical_date(iso)


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
    if slice_id:
        existing = await conn.fetchval(
            """
            SELECT id FROM scheduled_tasks
             WHERE task_type = 'theta_cycle' AND completed_at IS NULL
               AND payload->>'slice_id' = $1
             ORDER BY id LIMIT 1
            """,
            slice_id,
        )
    else:
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
    """Don't encode the empty ISO week that starts this Monday.

    Historical slices stay queued for Airflow backfill (one logical Monday at
    a time). Only the live calendar week — which has not closed — is dropped
    when we are consolidating a different slice.
    """
    from datetime import datetime, timezone

    live = get_week_slice_id(datetime.now(timezone.utc))
    if not live or live == current_slice:
        return 0
    return int(
        await conn.fetchval(
            """
            WITH u AS (
                UPDATE theta_consolidation_runs
                   SET status = 'superseded',
                       completed_at = NOW(),
                       error = $2
                 WHERE status = 'scheduled'
                   AND slice_id = $1
             RETURNING id
            )
            SELECT count(*)::int FROM u
            """,
            live,
            STALE_REASON,
        )
        or 0
    )


async def load_thoughts(
    conn: Any, slice_id: str, window_date: str = ""
) -> list[dict[str, Any]]:
    """Thoughts whose transaction time falls in this ISO week.

    A consolidation is the product of a slice, and a backfill lands later.
    It is not an input to the week its ``created_at`` happens to fall in.
    The optional UTC day is the LIGHT increment only.
    """
    sql = """
        SELECT id::text AS id, thought_type, title, content, summary,
               salience, domains, kb_paths
          FROM cognition_thoughts
         WHERE to_char(created_at AT TIME ZONE 'UTC', 'IYYY')
               || '-W' || to_char(created_at AT TIME ZONE 'UTC', 'IW')
               = $1
           AND thought_type IS DISTINCT FROM 'consolidation'
    """
    args: list[Any] = [slice_id]
    if window_date:
        sql += " AND (created_at AT TIME ZONE 'UTC')::date = $2::date"
        args.append(window_date)
    rows = await conn.fetch(sql, *args)
    return [dict(r) for r in rows]


async def start_current_job(
    conn: Any, slice_id: str
) -> tuple[int | None, int, dict[str, Any]]:
    superseded = await supersede_stale(conn, slice_id)
    rows = await conn.fetch("SELECT * FROM get_pending_theta_consolidations()")
    rows = [r for r in rows if str(r["slice_id"]) == slice_id]
    if not rows:
        job_id = await conn.fetchval("SELECT schedule_theta_consolidation($1)", slice_id)
        if job_id:
            rows = [{"job_id": job_id, "slice_id": slice_id}]
    if not rows:
        stuck = await conn.fetchrow(
            """
            SELECT id, metadata FROM theta_consolidation_runs
             WHERE slice_id = $1 AND status = 'running'
             ORDER BY id DESC LIMIT 1
            """,
            slice_id,
        )
        if stuck is None:
            return None, superseded, {}
        return int(stuck["id"]), superseded, as_meta_dict(stuck["metadata"])
    job_id = int(rows[0]["job_id"])
    started = await conn.fetchval("SELECT start_theta_consolidation($1)", job_id)
    if not started:
        meta_row = await conn.fetchrow(
            "SELECT metadata FROM theta_consolidation_runs WHERE id = $1", job_id
        )
        meta = {} if meta_row is None else as_meta_dict(meta_row["metadata"])
        return job_id, superseded, meta
    meta_row = await conn.fetchrow(
        "SELECT metadata FROM theta_consolidation_runs WHERE id = $1", job_id
    )
    meta = {} if meta_row is None else as_meta_dict(meta_row["metadata"])
    return job_id, superseded, meta


async def complete_job(dsn: str, job_id: int, result: dict[str, Any]) -> None:
    """Write the week artifact. A daily window refines it; completion is week-level."""
    import asyncpg

    signal = result.get("signal") or {}
    slice_id = str(result.get("slice_id") or "")
    window = utc_day(result.get("window_date") or "")
    success = bool(result.get("success"))
    err = None if success else (result.get("error") or result.get("guru_code") or GURU)
    patch = as_meta_dict(result.get("metadata"))
    pool = await asyncpg.create_pool(dsn)
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT metadata, slice_id, candidates_evaluated, documents_augmented "
                "FROM theta_consolidation_runs "
                "WHERE id = $1 AND status = 'running'",
                job_id,
            )
            if row is None:
                return
            meta = as_meta_dict(row["metadata"])
            sid = slice_id or str(row["slice_id"] or "")
            windows = [str(w)[:10] for w in (meta.get("windows") or [])]
            if window:
                if window not in windows:
                    windows.append(window)
                windows.sort()
            elif success:
                windows = iso_week_days(sid)
            meta["windows"] = windows
            for key in ("centroid", "n_encoded", "item_groundings"):
                if key in patch:
                    meta[key] = patch[key]
            thought_id = str(result.get("consolidation_thought_id") or "").strip()
            if thought_id:
                meta["consolidation_thought_id"] = thought_id
            if not success:
                errors = dict(meta.get("window_errors") or {})
                errors[window or "week"] = err
                meta["window_errors"] = errors
            add_evaluated = int(result.get("candidates_evaluated") or 0)
            add_augmented = int(result.get("documents_augmented") or 0)
            status, err_col = completion_status(
                success=success,
                windows_done=week_is_complete(windows, sid),
                has_window=bool(window),
                total_evaluated=int(row["candidates_evaluated"] or 0) + add_evaluated,
                total_augmented=int(row["documents_augmented"] or 0) + add_augmented,
                err=err,
                has_understanding=bool(thought_id),
            )
            await conn.execute(
                """
                UPDATE theta_consolidation_runs
                   SET status = $2,
                       completed_at = CASE WHEN $2 = 'completed' THEN NOW() ELSE NULL END,
                       urgency = COALESCE($3, urgency),
                       drift = COALESCE($4, drift),
                       candidates_evaluated = candidates_evaluated + $5,
                       candidates_selected = candidates_selected + $6,
                       documents_augmented = documents_augmented + $7,
                       error = $8,
                       metadata = $9::jsonb
                 WHERE id = $1 AND status = 'running'
                """,
                job_id,
                status,
                signal.get("urgency"),
                signal.get("drift"),
                int(result.get("candidates_evaluated") or 0),
                int(result.get("candidates_selected") or 0),
                int(result.get("documents_augmented") or 0),
                err_col,
                json.dumps(meta),
            )
            return status
    finally:
        await pool.close()

