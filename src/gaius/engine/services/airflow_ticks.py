"""Durable Airflow success times for the coordination hub.

``scheduled_tasks`` keeps only a short tail: Sunday's cleanup deletes every
row outside the newest thousand, and the per-minute jobs fill that thousand
in hours. A Friday or Monday success then looks like it never ran, and
Engine/Status tells the session the tick was missed.

This table is one row per workload. The hub reads it beside the task table.
Airflow's own successful DAG run is the execution record; a local completion
updates the same row.
"""
from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any

log = logging.getLogger(__name__)

_DDL = """
CREATE TABLE IF NOT EXISTS meta.airflow_workload_ticks (
    task_type text PRIMARY KEY,
    completed_at timestamptz NOT NULL,
    dag_id text NOT NULL DEFAULT '',
    dag_run_id text NOT NULL DEFAULT '',
    outcome text NOT NULL DEFAULT ''
)
"""

LAST_NOTED_TICK_SQL = (
    "SELECT completed_at FROM meta.airflow_workload_ticks WHERE task_type = $1"
)

_ensured = False


def later(a: datetime | None, b: datetime | None) -> datetime | None:
    if a is None:
        return b
    if b is None:
        return a
    return a if a >= b else b


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


async def ensure_tick_table(pool: Any) -> None:
    global _ensured
    if _ensured:
        return
    await pool.execute(_DDL)
    _ensured = True


async def note_airflow_tick(
    pool: Any,
    task_type: str,
    completed_at: datetime | None = None,
    *,
    dag_id: str = "",
    dag_run_id: str = "",
    outcome: str = "success",
) -> bool:
    """Record a success if it is newer than the row we already have."""
    kind = (task_type or "").strip()
    if not kind:
        return False
    when = _aware(completed_at or datetime.now(timezone.utc))
    await ensure_tick_table(pool)
    row = await pool.fetchrow(
        """
        INSERT INTO meta.airflow_workload_ticks
            (task_type, completed_at, dag_id, dag_run_id, outcome)
        VALUES ($1, $2, $3, $4, $5)
        ON CONFLICT (task_type) DO UPDATE
            SET completed_at = EXCLUDED.completed_at,
                dag_id = EXCLUDED.dag_id,
                dag_run_id = EXCLUDED.dag_run_id,
                outcome = EXCLUDED.outcome
          WHERE EXCLUDED.completed_at > meta.airflow_workload_ticks.completed_at
        RETURNING task_type
        """,
        kind,
        when,
        dag_id or "",
        dag_run_id or "",
        outcome or "",
    )
    return row is not None


def _airflow_cfg() -> tuple[str, str, str]:
    url = (os.environ.get("AIRFLOW_API_URL") or "http://127.0.0.1:30800").rstrip("/")
    user = os.environ.get("AIRFLOW_ADMIN_USER") or "admin"
    password = os.environ.get("AIRFLOW_ADMIN_PASSWORD") or "admin"
    return url, user, password


def _json(method: str, url: str, body: dict | None = None, token: str = "") -> Any:
    data = None if body is None else json.dumps(body).encode()
    headers = {"Accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=8) as resp:
        return json.loads(resp.read().decode() or "{}")


def airflow_latest_successes() -> list[tuple[str, datetime, str, str]]:
    """Latest successful DAG run per enabled catalogue workload.

    Fail-soft: an unreachable Airflow returns nothing and the hub keeps the
    ticks it already has. Peers still do not schedule through this URL; it
    is only how Gaius reads the runs Signals already materialised.
    """
    from gaius.engine.services.workload_catalog import airflow_dag_id, enabled_entries

    url, user, password = _airflow_cfg()
    try:
        token = str(
            _json("POST", f"{url}/auth/token", {"username": user, "password": password}).get(
                "access_token"
            )
            or ""
        )
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as e:
        log.warning("airflow tick reconcile: login failed: %s", e)
        return []
    if not token:
        log.warning("airflow tick reconcile: login returned no token")
        return []
    out: list[tuple[str, datetime, str, str]] = []
    for entry in enabled_entries():
        dag_id = airflow_dag_id(entry)
        if not dag_id:
            continue
        try:
            payload = _json(
                "GET",
                f"{url}/api/v2/dags/{dag_id}/dagRuns?limit=5&order_by=-end_date",
                token=token,
            )
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as e:
            log.warning("airflow tick reconcile: %s: %s", dag_id, e)
            continue
        for run in payload.get("dag_runs") or []:
            if str(run.get("state") or "") != "success":
                continue
            raw = str(run.get("end_date") or run.get("start_date") or "")
            if not raw:
                continue
            try:
                when = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            except ValueError:
                continue
            out.append((entry.task_type, _aware(when), dag_id, str(run.get("dag_run_id") or "")))
            break
    return out


async def reconcile_airflow_ticks(pool: Any) -> int:
    """Upsert successes Airflow already recorded. Returns how many moved forward."""
    import asyncio

    found = await asyncio.to_thread(airflow_latest_successes)
    moved = 0
    for task_type, when, dag_id, run_id in found:
        if await note_airflow_tick(
            pool, task_type, when, dag_id=dag_id, dag_run_id=run_id, outcome="airflow-success"
        ):
            moved += 1
            log.info("airflow tick %s at %s run=%s", task_type, when.isoformat(), run_id)
    return moved
