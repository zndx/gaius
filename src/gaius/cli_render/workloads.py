"""Text rendering for /workloads (pure; no I/O).

One line per catalogue entry: where its schedule lives, the cadence (or what
it follows), the runner, the claims it asserts while it runs, and what Signals
made of it at the last sync.
"""

from __future__ import annotations

from typing import Any

_SOURCE = {"airflow": "▶", "pg_cron": "◦"}
_SYNC = {"materialized": "materialized", "paused": "paused", "engine_declared": "engine", "error": "ERROR"}


def render_workloads(
    rows: list[dict[str, Any]],
    *,
    signals_target: str = "",
    last_sync_at: str = "",
    last_sync_error: str = "",
) -> str:
    head = "workload catalogue"
    if last_sync_at:
        head += f" · submitted to {signals_target} at {last_sync_at}"
    elif signals_target:
        head += f" · NOT yet submitted to {signals_target}"
    if last_sync_error:
        head += f" · last sync error: {last_sync_error}"
    lines = [head]
    if not rows:
        lines.append("  (empty)")
        return "\n".join(lines)
    enabled = sum(1 for r in rows if r.get("enabled"))
    lines.append(f"  {len(rows)} classes · {enabled} scheduled in Airflow · {len(rows) - enabled} on pg_cron (catalogued paused)")
    for r in rows:
        g = _SOURCE.get(str(r.get("source") or ""), "?")
        when = r.get("cron") or ("after " + ", ".join(r.get("after") or []) if r.get("after") else "unscheduled")
        if r.get("after") and r.get("cron"):
            when += " · after " + ", ".join(r["after"])
        claims = ", ".join(r.get("claims") or []) or "no GPU"
        sync = _SYNC.get(str(r.get("sync_state") or ""), r.get("sync_state") or "unsynced")
        lines.append(
            f"  {g} {r.get('kind') or '?':<26} {when:<24} {r.get('runner') or '?':<8} {claims:<40} {sync}"
        )
        detail: list[str] = []
        if r.get("airflow_dag_id"):
            detail.append(f"dag {r['airflow_dag_id']}")
        if r.get("pg_cron_job"):
            detail.append(f"pg_cron {r['pg_cron_job']}" + ("" if r.get("pg_cron_active", True) else " (inactive)"))
        if r.get("horizon_s"):
            detail.append(f"horizon {int(r['horizon_s']) // 3600} h")
        if r.get("gate_sql"):
            detail.append(f"gate {r['gate_sql']}")
        if r.get("sync_error"):
            detail.append(f"sync error: {r['sync_error']}")
        if detail:
            lines.append("      " + "; ".join(detail))
    return "\n".join(lines)
