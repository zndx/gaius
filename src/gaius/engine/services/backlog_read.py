"""Read the Operations Backlog for `/backlog` and EngineSupervision.Backlog.

The rows live in the project's tiered store: the resident Nautilus writes Kudu
tier0 through the impala_fdw foreign table ``nautilus_backlog_tier0`` and the
Impala union view ``nautilus_backlog`` (tier0 ∪ tier1) is what everyone reads —
this engine, Metabase, peers. One row per (workflow, slot, window) with the
latest fill winning; the response is one BacklogRow per workflow with exactly
ten cells (slots 0..9; unfilled = UNSPECIFIED) over the trailing 34 h, the
escalation level being the deepest slot holding a miss.

kudu_scan foreign tables reject computed quals, so the epoch-hour bound is
computed here and BOUND as a literal. Absence of the view is a loud finding
(``#SV.00000010.NOBACKLOG``): the Backlog is not filling, or the FDW DDL has
not been applied to this database.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from gaius.engine.generated.zndx.supervision.v1 import supervision_pb2 as sv

logger = logging.getLogger(__name__)

GURU_NOBACKLOG = "#SV.00000010.NOBACKLOG"
WINDOW_HOURS = 34
FIB_HOURS = (0, 1, 1, 2, 3, 5, 8, 13, 21, 34)

_STATE = {
    "ok": sv.BACKLOG_STATE_OK, "deferred": sv.BACKLOG_STATE_DEFERRED, "missed": sv.BACKLOG_STATE_MISSED,
    "failed": sv.BACKLOG_STATE_FAILED, "judged_fail": sv.BACKLOG_STATE_JUDGED_FAIL,
    "awaiting": sv.BACKLOG_STATE_AWAITING, "unknown": sv.BACKLOG_STATE_UNKNOWN,
}
_CATEGORY = {
    "tick": sv.EXPECTATION_CATEGORY_TICK, "hourly_settled": sv.EXPECTATION_CATEGORY_HOURLY_SETTLED,
    "hourly-settled": sv.EXPECTATION_CATEGORY_HOURLY_SETTLED, "slot": sv.EXPECTATION_CATEGORY_SLOT,
    "daily_dependent": sv.EXPECTATION_CATEGORY_DAILY_DEPENDENT, "daily-dependent": sv.EXPECTATION_CATEGORY_DAILY_DEPENDENT,
    "judged": sv.EXPECTATION_CATEGORY_JUDGED, "chronic_audit": sv.EXPECTATION_CATEGORY_CHRONIC_AUDIT,
    "chronic-audit": sv.EXPECTATION_CATEGORY_CHRONIC_AUDIT, "operator_window": sv.EXPECTATION_CATEGORY_OPERATOR_WINDOW,
    "operator-window": sv.EXPECTATION_CATEGORY_OPERATOR_WINDOW, "transient": sv.EXPECTATION_CATEGORY_TRANSIENT,
}
_CHANNEL_BY_SLOT = {3: sv.CHANNEL_AGENDA_EVENT, 5: sv.CHANNEL_REMINDER, 6: sv.CHANNEL_BRIEFING,
                    8: sv.CHANNEL_BRIEFING, 9: sv.CHANNEL_DISCUSSION}


def channel_for_level(level: int) -> int:
    best = sv.CHANNEL_LOG if level > 0 else sv.CHANNEL_UNSPECIFIED
    for s, ch in _CHANNEL_BY_SLOT.items():
        if level >= s:
            best = ch
    return best


def rows_to_response(rows: list[dict[str, Any]], *, project: str, as_of_ms: int, epoch: str,
                     supervisor_connected: bool, include_ok: bool) -> sv.BacklogResponse:
    """Pure: latest cell per (item_key, slot) → one BacklogRow per ITEM.

    Items are keyed by (workflow, failure mode) — `task.x/deferred` and
    `task.x/missed` are two ladders and must not be merged into one row (the
    2026-09-04 first fill showed a verifier row climbing to L5 from two items'
    cells). A workflow's healthy marker — its latest `ok` at slot 0 — RESOLVES
    every item of that workflow whose last cell is older: the resident writes
    that marker only when no item is open, so it is the honest "healthy since"
    even across a resident restart or a spec change that retired the item.
    """
    by_item: dict[str, dict[str, Any]] = {}
    healthy_since: dict[str, int] = {}  # workflow → latest ok slot-0 filled_ms
    for r in rows:
        wf = str(r["workflow"])
        slot = int(r["slot"])
        item = str(r.get("item_key") or wf)
        ts_ns = int(r.get("ts_ns") or 0)
        filled = int(r.get("filled_ms") or (ts_ns // 1_000_000))
        if slot == 0 and str(r.get("state") or "") == "ok" and item == wf:
            healthy_since[wf] = max(healthy_since.get(wf, 0), filled)
        d = by_item.setdefault(item, {"workflow": wf, "cells": {}, "category": str(r.get("category") or ""), "item_key": item,
                                      "first_miss": 0, "horizon": 0, "horizon_slot": 0, "resolved": 0, "last_cell": 0})
        prev = d["cells"].get(slot)
        if prev is None or ts_ns > prev["ts_ns"]:
            d["cells"][slot] = {"ts_ns": ts_ns, "state": str(r.get("state") or ""), "window_start": int(r.get("window_start_ms") or 0),
                                "filled": filled, "evidence": r.get("evidence") or ""}
            d["first_miss"] = max(d["first_miss"], int(r.get("first_miss_ms") or 0))
            d["horizon"] = max(d["horizon"], int(r.get("horizon_ms") or 0))
            d["horizon_slot"] = max(d["horizon_slot"], int(r.get("horizon_slot") or 0))
            d["last_cell"] = max(d["last_cell"], filled)
            if r.get("resolved"):
                d["resolved"] = max(d["resolved"], filled)
    last_tick = 0
    out_rows: list[sv.BacklogRow] = []
    for item in sorted(by_item):
        d = by_item[item]
        wf = d["workflow"]
        slots = []
        level = 0
        for s in range(10):
            c = d["cells"].get(s)
            if c is None:
                slots.append(sv.BacklogSlot(slot=s))
                continue
            st = _STATE.get(c["state"], sv.BACKLOG_STATE_UNSPECIFIED)
            if st not in (sv.BACKLOG_STATE_OK, sv.BACKLOG_STATE_UNSPECIFIED):
                level = max(level, s)
            last_tick = max(last_tick, c["filled"])
            ev = c["evidence"]
            slots.append(sv.BacklogSlot(slot=s, state=st, window_start_unix_ms=c["window_start"], filled_unix_ms=c["filled"],
                                        evidence_json=ev if isinstance(ev, str) else json.dumps(ev, default=str)))
        resolved = d["resolved"]
        healthy = healthy_since.get(wf, 0)
        if item != wf and healthy > d["last_cell"]:
            resolved = max(resolved, healthy)  # a healthy tick after the item's last cell closes it
            level = 0
        if not include_ok and level == 0 and not d["cells"]:
            continue
        out_rows.append(sv.BacklogRow(
            workflow=wf, category=_CATEGORY.get(d["category"].lower(), sv.EXPECTATION_CATEGORY_UNSPECIFIED),
            horizon_slot=d["horizon_slot"], slots=slots, escalation_level=level, channel=channel_for_level(level),
            item_key=d["item_key"], first_miss_unix_ms=d["first_miss"], horizon_unix_ms=d["horizon"],
            resolved_unix_ms=resolved,
        ))
    if not include_ok:
        out_rows = [r for r in out_rows if r.escalation_level > 0]
    return sv.BacklogResponse(project=project, as_of_unix_ms=as_of_ms, last_tick_unix_ms=last_tick,
                              supervisor_connected=supervisor_connected, epoch=epoch, rows=out_rows)


def declared_workflows(spec: Any) -> set[str] | None:
    """The Backlog workflows the CURRENT instance declares: cadenced processes with
    an expectation (pg_cron jobs excluded — the stream carries no job_run_details,
    so the resident does not fill them) plus `objective.<name>` for objectives with
    an expectation. None when the spec is unavailable (no filtering)."""
    sup = getattr(spec, "supervisor", None)
    if sup is None:
        return None
    out: set[str] = set()
    procs = list(getattr(sup, "processes", []))
    with_expectation = {p.id for p in procs if (p.HasField("expectation") if hasattr(p, "HasField") else getattr(p, "expectation", None) is not None)}
    for p in procs:
        cad = getattr(p, "cadence", None)
        if cad is None or (not cad.cron and not cad.expected_period_seconds):
            continue
        if p.id not in with_expectation:
            continue
        if p.kind == sv.PROCESS_KIND_PG_CRON_JOB:
            continue
        # A Metaflow flow mirrors its parent task class (the task row carries the
        # events); the resident folds it into the parent — same rule here, or the
        # ops_backlog gate lists flow.* as "missing" forever (2026-09-05 01:38).
        if p.kind == sv.PROCESS_KIND_METAFLOW_FLOW and p.parent and p.parent in with_expectation:
            continue
        out.add(p.id)
    for o in getattr(sup, "objectives", []):
        has = o.HasField("expectation") if hasattr(o, "HasField") else getattr(o, "expectation", None) is not None
        if has:
            out.add(f"objective.{o.name}")
    return out


async def read_backlog(pool: Any, request: sv.BacklogRequest, *, epoch: str, supervisor_connected: bool,
                       declared: set[str] | None = None) -> sv.BacklogResponse:
    as_of_ms = int(request.as_of_unix_ms or int(time.time() * 1000))
    project = request.project or "gaius"
    since_hour = as_of_ms // 3_600_000 - WINDOW_HOURS - 1
    sql = (
        "SELECT epoch_hour, ts_ns, workflow, item_key, slot, state, category, first_miss_ns, horizon_slot, horizon_ns, "
        "escalation_level, resolved, evidence "
        "FROM nautilus_backlog WHERE project = $1 AND epoch_hour >= $2"
        + (" AND workflow = $3" if request.workflow else "")
    )
    args: list[Any] = [project, int(since_hour)] + ([request.workflow] if request.workflow else [])
    try:
        async with pool.acquire() as conn:
            recs = await conn.fetch(sql, *args)
    except Exception as e:  # noqa: BLE001 — the view's absence is the finding
        raise RuntimeError(
            f"{GURU_NOBACKLOG} nautilus_backlog unreadable ({str(e)[:160]}).\n"
            "  The Backlog is not filling, or the FDW DDL is not applied to this database.\n"
            "  Try: devenv processes restart nautilus; just warehouse-fdw; /nautilus status"
        ) from e
    if declared is not None:
        # Rows for workflows the instance no longer declares (or never should have:
        # the pg_cron enqueuers of 2026-09-04) stay in the store as history but are
        # not the CURRENT state table.
        recs = [r for r in recs if r["workflow"] in declared or r["workflow"] == "engine"]
    rows = [{
        "workflow": r["workflow"], "slot": r["slot"], "ts_ns": r["ts_ns"], "state": r["state"], "category": r["category"],
        "item_key": r["item_key"], "window_start_ms": int(r["epoch_hour"]) * 3_600_000, "filled_ms": int(r["ts_ns"]) // 1_000_000,
        "first_miss_ms": int(r["first_miss_ns"] or 0) // 1_000_000, "horizon_ms": int(r["horizon_ns"] or 0) // 1_000_000,
        "horizon_slot": r["horizon_slot"], "resolved": r["resolved"], "evidence": r["evidence"],
    } for r in recs]
    return rows_to_response(rows, project=project, as_of_ms=as_of_ms, epoch=epoch,
                            supervisor_connected=supervisor_connected, include_ok=bool(request.include_ok) or True)
