"""Replay of supervision events from the engine's own tables.

When the resident Nautilus (re)connects it sends ``Subscribe{since_unix_ms}``.
The engine's tables are the write-ahead log for everything the supervisor has
not acked, so this module derives the same events the live bus would have
emitted, from the rows that record them:

* ``scheduled_tasks`` — CLAIMED at ``picked_up_at``, HEARTBEAT at
  ``heartbeat_at``, the terminal state at ``completed_at`` from
  ``result->>'status'`` / ``error`` (a deferral is a clean row with
  ``status='deferred'`` — it MUST surface as DEFERRED, the Backlog's slot-0
  entry; ``error IS NULL`` is not success);
* ``probe_forecasts`` where ``observer LIKE 'watchdog:%'`` — RESET (the reset
  itself never stamps a time on the task row; the forecast is its only record);
* ``objective_verifications`` — the verdict at ``completed_at``/``started_at``;
* ``healing_events`` — incident open / tier / close.

The derivation is pure over row dicts (``events_from_*``) so it is unit-testable
without a database; ``replay_events`` only runs the SQL. Events carry the SOURCE
timestamp and ``replayed=True``; the ordering key is
``(at_unix_ms, source_rank, row_id)`` so replayed and live streams interleave
deterministically. ``since`` older than the window is clamped
(``#SV.00000004.REPLAYCLAMP``) — nothing deeper than the Backlog's 34 h slot is
ever needed.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from gaius.engine.services.supervision_bus import (
    KIND_ADMISSION,
    KIND_INCIDENT,
    KIND_OBJECTIVE,
    KIND_TASK,
    SupervisionEvent,
)

logger = logging.getLogger(__name__)

GURU_REPLAYCLAMP = "#SV.00000004.REPLAYCLAMP"

REPLAY_WINDOW_HOURS = 48
_RANK = {"scheduled_tasks": 0, "probe_forecasts": 1, "objective_verifications": 2, "healing_events": 3}

_TERMINAL = {
    "completed": "COMPLETED",
    "deferred": "DEFERRED",
    "failed": "FAILED",
    "error": "ERROR",
    "stalled": "STALLED",
    "yielded": "YIELDED",
    "skipped": "SKIPPED",
}


def _ms(ts: Any) -> int | None:
    if ts is None:
        return None
    if isinstance(ts, datetime):
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return int(ts.timestamp() * 1000)
    return int(ts)


def _ev(kind: str, at_ms: int, payload: dict[str, Any]) -> SupervisionEvent:
    return SupervisionEvent(seq=0, at_unix_ms=at_ms, kind=kind, payload=payload, replayed=True)


# ── pure derivations ────────────────────────────────────────────────────────

def events_from_task_row(row: dict[str, Any], since_ms: int) -> list[tuple[tuple, SupervisionEvent]]:
    """CLAIMED / HEARTBEAT / terminal (+ a synthetic admission for deferrals)."""
    out: list[tuple[tuple, SupervisionEvent]] = []
    tid = int(row["id"])
    ttype = str(row["task_type"])
    result = row.get("result") or {}
    if isinstance(result, str):
        import json as _json

        try:
            result = _json.loads(result)
        except Exception:  # noqa: BLE001
            result = {}
    base = {
        "task_id": tid,
        "task_type": ttype,
        "source": str(row.get("source") or ""),
        "scheduled_for_unix_ms": _ms(row.get("scheduled_for")) or 0,
        "picked_up_unix_ms": _ms(row.get("picked_up_at")) or 0,
        "heartbeat_unix_ms": _ms(row.get("heartbeat_at")) or 0,
        "completed_unix_ms": _ms(row.get("completed_at")) or 0,
        "workload_id": str(result.get("workload_id") or "") if isinstance(result, dict) else "",
    }
    picked = _ms(row.get("picked_up_at"))
    if picked is not None and picked >= since_ms:
        out.append(((picked, _RANK["scheduled_tasks"], tid, 0), _ev(KIND_TASK, picked, {**base, "state": "CLAIMED"})))
    hb = _ms(row.get("heartbeat_at"))
    if hb is not None and hb >= since_ms and (picked is None or hb > picked):
        out.append(((hb, _RANK["scheduled_tasks"], tid, 1), _ev(KIND_TASK, hb, {**base, "state": "HEARTBEAT"})))
    done = _ms(row.get("completed_at"))
    if done is not None and done >= since_ms:
        status = str(result.get("status") or "") if isinstance(result, dict) else ""
        err = row.get("error")
        if not status:
            status = "error" if err else "completed"
        state = _TERMINAL.get(status, "COMPLETED")
        if err and state == "COMPLETED":
            state = "ERROR"
        reason = str(result.get("reason") or "") if isinstance(result, dict) else ""
        out.append(((done, _RANK["scheduled_tasks"], tid, 2), _ev(KIND_TASK, done, {**base, "state": state, "reason": reason, "error": (str(err)[:300] if err else "")})))
        if state == "DEFERRED":
            out.append(((done, _RANK["scheduled_tasks"], tid, 3), _ev(KIND_ADMISSION, done, {
                "task_id": tid, "kind": ttype.replace("_", "-"), "workload_id": base["workload_id"],
                "phase": "NOTADMITTED", "reason": reason,
            })))
    return out


def events_from_forecast_row(row: dict[str, Any]) -> list[tuple[tuple, SupervisionEvent]]:
    """A watchdog forecast is the only timestamped record of a claim reset."""
    at = _ms(row.get("created_at"))
    if at is None:
        return []
    tid = int(row.get("task_id") or 0)
    return [((at, _RANK["probe_forecasts"], int(row.get("id") or 0), 0), _ev(KIND_TASK, at, {
        "task_id": tid, "task_type": str(row.get("task_class") or ""), "state": "RESET",
        "reason": "watchdog" if "pg_cron" in str(row.get("observer") or "") else "orphan",
        "error": str(row.get("proposition") or "")[:300], "source": "", "workload_id": "",
        "scheduled_for_unix_ms": 0, "picked_up_unix_ms": 0, "heartbeat_unix_ms": 0, "completed_unix_ms": 0,
    }))]


def events_from_verification_row(row: dict[str, Any]) -> list[tuple[tuple, SupervisionEvent]]:
    at = _ms(row.get("completed_at")) or _ms(row.get("started_at"))
    if at is None:
        return []
    gates = row.get("gate_results") or []
    if isinstance(gates, str):
        import json as _json

        try:
            gates = _json.loads(gates)
        except Exception:  # noqa: BLE001
            gates = []
    judge = any(str(g.get("authority") or "") == "overwatch-grok" for g in gates if isinstance(g, dict))
    return [((at, _RANK["objective_verifications"], int(row.get("id") or 0), 0), _ev(KIND_OBJECTIVE, at, {
        "objective": str(row.get("objective_name") or ""), "run_id": str(row.get("run_id") or ""),
        "verdict": str(row.get("verdict") or "").upper(), "gates_passed": int(row.get("gates_passed") or 0),
        "gates_total": int(row.get("gates_total") or 0), "judge_rendered": judge,
        "started_unix_ms": _ms(row.get("started_at")) or 0, "completed_unix_ms": _ms(row.get("completed_at")) or 0,
        "gates": [{"name": str(g.get("gate") or g.get("name") or ""), "verdict": str(g.get("verdict") or "").upper(),
                   "detail": str(g.get("evidence") or g.get("detail") or "")[:300]} for g in gates if isinstance(g, dict)],
    }))]


_INCIDENT_STATE = {
    "sequence_started": "ACTIVE",
    "tier_entered": "HEALING",
    "recovery_started": "RECOVERING",
    "sequence_completed": "RESOLVED",
    "manual_required": "MANUAL_REQUIRED",
}


def events_from_healing_row(row: dict[str, Any]) -> list[tuple[tuple, SupervisionEvent]]:
    at = _ms(row.get("created_at"))
    if at is None:
        return []
    et = str(row.get("event_type") or "")
    payload = row.get("payload") or {}
    if isinstance(payload, str):
        import json as _json

        try:
            payload = _json.loads(payload)
        except Exception:  # noqa: BLE001
            payload = {}
    fm = str(payload.get("failure_mode_id") or row.get("failure_mode_id") or "")
    ep = str(row.get("endpoint") or "")
    return [((at, _RANK["healing_events"], int(row.get("id") or 0), 0), _ev(KIND_INCIDENT, at, {
        "fingerprint": f"{fm}:{ep}" if fm else ep, "state": _INCIDENT_STATE.get(et, "ACTIVE"),
        "tier": int(row.get("tier") or 0), "endpoint": ep, "failure_mode": fm,
        "sequence_id": str(row.get("sequence_id") or ""), "sequence_num": int(row.get("sequence_num") or 0),
        "event_type": et,
    }))]


def order_events(keyed: list[tuple[tuple, SupervisionEvent]]) -> list[SupervisionEvent]:
    keyed.sort(key=lambda kv: kv[0])
    return [ev for _, ev in keyed]


# ── the SQL ─────────────────────────────────────────────────────────────────

async def replay_events(pool: Any, since_ms: int, until_ms: int | None = None) -> tuple[list[SupervisionEvent], dict[str, Any]]:
    """Replay [since, until] from the tables. Returns (events, meta{clamped, tables, since})."""
    import time as _time

    now_ms = int(_time.time() * 1000)
    until = int(until_ms or now_ms)
    floor_ms = now_ms - REPLAY_WINDOW_HOURS * 3600 * 1000
    clamped = False
    if since_ms <= 0:
        since_ms = until  # live only
    if since_ms < floor_ms:
        logger.info("%s replay since clamped from %s to %s", GURU_REPLAYCLAMP, since_ms, floor_ms)
        since_ms = floor_ms
        clamped = True
    since_dt = datetime.fromtimestamp(since_ms / 1000, tz=timezone.utc)
    until_dt = datetime.fromtimestamp(until / 1000, tz=timezone.utc)
    keyed: list[tuple[tuple, SupervisionEvent]] = []
    tables: list[str] = []
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, task_type, source, scheduled_for, picked_up_at, heartbeat_at,
                   completed_at, result, error
              FROM scheduled_tasks
             WHERE GREATEST(created_at, picked_up_at, heartbeat_at, completed_at) >= $1
               AND GREATEST(created_at, picked_up_at, heartbeat_at, completed_at) <= $2
            """,
            since_dt, until_dt,
        )
        tables.append("scheduled_tasks")
        for r in rows:
            keyed.extend(events_from_task_row(dict(r), since_ms))
        rows = await conn.fetch(
            """
            SELECT id, created_at, observer, proposition, task_class, task_id
              FROM probe_forecasts
             WHERE observer LIKE 'watchdog:%' AND created_at >= $1 AND created_at <= $2
            """,
            since_dt, until_dt,
        )
        tables.append("probe_forecasts")
        for r in rows:
            keyed.extend(events_from_forecast_row(dict(r)))
        rows = await conn.fetch(
            """
            SELECT id, objective_name, run_id, verdict, gates_passed, gates_total,
                   gate_results, started_at, completed_at
              FROM objective_verifications
             WHERE COALESCE(completed_at, started_at) >= $1 AND COALESCE(completed_at, started_at) <= $2
            """,
            since_dt, until_dt,
        )
        tables.append("objective_verifications")
        for r in rows:
            keyed.extend(events_from_verification_row(dict(r)))
        rows = await conn.fetch(
            """
            SELECT id, created_at, event_type, endpoint, tier, sequence_id, sequence_num,
                   payload, failure_mode_id
              FROM healing_events
             WHERE created_at >= $1 AND created_at <= $2
               AND event_type IN ('sequence_started','tier_entered','recovery_started',
                                  'sequence_completed','manual_required')
            """,
            since_dt, until_dt,
        )
        tables.append("healing_events")
        for r in rows:
            keyed.extend(events_from_healing_row(dict(r)))
    events = order_events(keyed)
    return events, {"clamped": clamped, "tables": tables, "since_unix_ms": since_ms, "until_unix_ms": until}
