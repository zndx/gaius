"""The engine-side Backlog read model (backlog_read.rows_to_response / declared_workflows)."""

from __future__ import annotations

from types import SimpleNamespace

from gaius.engine.generated.zndx.supervision.v1 import supervision_pb2 as sv
from gaius.engine.services.backlog_read import declared_workflows, rows_to_response

H = 3_600_000
T0 = 1_788_552_000_000  # 2026-09-04 20:00Z


def cell(workflow, item, slot, state, at_ms, **kw):
    return {"workflow": workflow, "item_key": item, "slot": slot, "state": state, "ts_ns": at_ms * 1_000_000,
            "filled_ms": at_ms, "window_start_ms": (at_ms // H) * H, "category": kw.get("category", "tick"),
            "first_miss_ms": kw.get("first_miss_ms", 0), "horizon_ms": kw.get("horizon_ms", 0),
            "horizon_slot": kw.get("horizon_slot", 3), "resolved": kw.get("resolved", False), "evidence": ""}


def test_items_of_one_workflow_are_separate_rows() -> None:
    rows = [
        cell("task.v", "task.v/failed", 0, "failed", T0, category="slot"),
        cell("task.v", "task.v/failed", 1, "failed", T0 + H, category="slot"),
        cell("task.v", "task.v/missed", 0, "missed", T0 - 5 * H, category="slot"),
        cell("task.v", "task.v/missed", 5, "missed", T0 + H, category="slot"),
    ]
    resp = rows_to_response(rows, project="gaius", as_of_ms=T0 + 2 * H, epoch="e", supervisor_connected=True, include_ok=True)
    keys = {r.item_key: r.escalation_level for r in resp.rows}
    assert keys == {"task.v/failed": 1, "task.v/missed": 5}, keys
    failed = next(r for r in resp.rows if r.item_key == "task.v/failed")
    assert failed.slots[5].state == sv.BACKLOG_STATE_UNSPECIFIED  # not merged from the other item


def test_healthy_marker_after_the_item_resolves_it() -> None:
    rows = [
        cell("task.v", "task.v/failed", 0, "failed", T0),
        cell("task.v", "task.v/failed", 1, "failed", T0 + H),
        cell("task.v", "task.v", 0, "ok", T0 + 2 * H),  # the resident's healthy tick: no open item
    ]
    resp = rows_to_response(rows, project="gaius", as_of_ms=T0 + 3 * H, epoch="e", supervisor_connected=True, include_ok=True)
    item = next(r for r in resp.rows if r.item_key == "task.v/failed")
    assert item.resolved_unix_ms == T0 + 2 * H
    assert item.escalation_level == 0
    # a healthy tick BEFORE the item's last cell does not resolve it
    rows2 = rows[:2] + [cell("task.v", "task.v", 0, "ok", T0 - H)]
    resp2 = rows_to_response(rows2, project="gaius", as_of_ms=T0 + 3 * H, epoch="e", supervisor_connected=True, include_ok=True)
    item2 = next(r for r in resp2.rows if r.item_key == "task.v/failed")
    assert item2.escalation_level == 1 and item2.resolved_unix_ms == 0


def test_declared_workflows_excludes_pg_cron_and_adds_objectives() -> None:
    p_task = sv.Process(id="task.x", kind=sv.PROCESS_KIND_SCHEDULED_TASK, cadence=sv.Cadence(cron="*/15 * * * *", net_seconds=900),
                        expectation=sv.Expectation(category=sv.EXPECTATION_CATEGORY_TICK, horizon_slot=3))
    p_cron = sv.Process(id="cron.x", kind=sv.PROCESS_KIND_PG_CRON_JOB, cadence=sv.Cadence(cron="20 * * * *", net_seconds=900),
                        expectation=sv.Expectation(category=sv.EXPECTATION_CATEGORY_TICK, horizon_slot=3))
    p_noexp = sv.Process(id="task.y", kind=sv.PROCESS_KIND_SCHEDULED_TASK, cadence=sv.Cadence(cron="0 * * * *"))
    # a flow folded into its declared parent task class is not a workflow of its own
    p_flow = sv.Process(id="flow.XFlow", kind=sv.PROCESS_KIND_METAFLOW_FLOW, parent="task.x", cadence=sv.Cadence(cron="*/15 * * * *", net_seconds=900),
                        expectation=sv.Expectation(category=sv.EXPECTATION_CATEGORY_TICK, horizon_slot=3))
    obj = sv.Objective(name="prospects_intelligence", expectation=sv.Expectation(category=sv.EXPECTATION_CATEGORY_JUDGED, horizon_slot=7))
    obj2 = sv.Objective(name="site_freshness")
    sup = sv.Supervisor(project="gaius", processes=[p_task, p_cron, p_noexp, p_flow], objectives=[obj, obj2])
    assert declared_workflows(SimpleNamespace(supervisor=sup)) == {"task.x", "objective.prospects_intelligence"}
    assert declared_workflows(SimpleNamespace(supervisor=None)) is None
