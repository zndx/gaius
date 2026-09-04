"""The /backlog text rendering (pure) and the CLI's row shape."""

from __future__ import annotations

from datetime import datetime, timezone

from gaius.cli_render.backlog import pending_slot, render_backlog

AS_OF = datetime(2026, 9, 4, 15, 41, tzinfo=timezone.utc)


def _row(workflow, states, level=0, **kw):
    slots = [{"slot": i, "f_hours": f, "state": s} for i, (f, s) in enumerate(zip((0, 1, 1, 2, 3, 5, 8, 13, 21, 34), states))]
    return {"workflow": workflow, "category": kw.get("category", "tick"), "slots": slots, "escalation_level": level,
            "channel": kw.get("channel"), "first_miss_at": kw.get("first_miss_at"), "resolved_at": kw.get("resolved_at")}


def test_case_a_row_renders_ladder_and_pending_arrow() -> None:
    row = _row("task.clt_skos_admit", ["missed"] * 6 + [""] * 4, level=5, channel="reminder", first_miss_at="2026-09-04T09:10:00+00:00")
    # 15:41: age 6.5 h — slot 6 (F=8 h) is not due yet, no arrow
    text = render_backlog([row], as_of=AS_OF)
    line = [ln for ln in text.splitlines() if ln.startswith("task.clt_skos_admit")][0]
    assert "  M   M   M   M   M   M   ·   ·   ·   ·" in line
    assert line.rstrip().endswith("L5 reminder")
    # 17:41: age 8.5 h — slot 6 crossed but not yet evaluated by the hourly circuit → ↑
    later = datetime(2026, 9, 4, 17, 41, tzinfo=timezone.utc)
    line = [ln for ln in render_backlog([row], as_of=later).splitlines() if ln.startswith("task.clt_skos_admit")][0]
    assert "  M   M   M   M   M   M   ↑   ·   ·   ·" in line


def test_healthy_row_is_ok_at_slot_zero_only() -> None:
    row = _row("task.tier_settle", ["ok"] + [""] * 9, category="hourly_settled")
    text = render_backlog([row], as_of=AS_OF, filled_at="2026-09-04T15:01:00+00:00", supervisor_connected=True)
    assert " ok   ·   ·   ·   ·   ·   ·   ·   ·   ·" in text
    assert "hrly-set" in text and "supervisor connected" in text


def test_pending_slot_needs_age_and_previous_slot() -> None:
    row = _row("w", ["missed", "missed", "missed"] + [""] * 7, first_miss_at="2026-09-04T13:41:00+00:00")  # age 2 h
    assert pending_slot(row, AS_OF) == 3  # F(3)=2 h crossed, slot 2 filled
    row2 = _row("w", ["missed"] + [""] * 9, first_miss_at="2026-09-04T15:20:00+00:00")  # age 21 min
    assert pending_slot(row2, AS_OF) is None
    row3 = _row("w", ["missed"] * 6 + [""] * 4, first_miss_at="2026-09-04T09:10:00+00:00", resolved_at="2026-09-04T15:00:00+00:00")
    assert pending_slot(row3, AS_OF) is None  # resolved items do not grow


def test_open_items_sort_first_and_empty_is_loud() -> None:
    rows = [_row("a", ["ok"] + [""] * 9), _row("b", ["deferred", "deferred", "deferred", "deferred"] + [""] * 6, level=3, channel="agenda_event")]
    text = render_backlog(rows, as_of=AS_OF)
    lines = [ln for ln in text.splitlines() if ln[:1] in "ab"]
    assert lines[0].startswith("b") and "L3 agenda_event" in lines[0]
    assert "no backlog rows" in render_backlog([], as_of=AS_OF)
