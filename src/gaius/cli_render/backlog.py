"""Render the Operations Backlog: one row per workflow, ten Fibonacci-hour cells.

    workflow                    cat        0   1   1   2   3   5   8  13  21  34   level
    task.clt_skos_admit         tick       M   M   M   M   M   M   ↑   ·   ·   ·   L6 briefing
    task.tier_settle            hrly-set   ok  ·   ·   ·   ·   ·   ·   ·   ·   ·

Glyphs: ok | D deferred | M missed | F failed | J judged_fail | A awaiting | ? unknown
| · unfilled | ↑ the next slot whose F-hour the item's age has crossed but the
hourly circuit has not yet evaluated.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

FIB_HOURS = (0, 1, 1, 2, 3, 5, 8, 13, 21, 34)
GLYPH = {"ok": "ok", "deferred": "D", "missed": "M", "failed": "F", "judged_fail": "J", "awaiting": "A", "unknown": "?", "": "·"}
CAT_SHORT = {"tick": "tick", "hourly_settled": "hrly-set", "slot": "slot", "daily_dependent": "daily-dep", "judged": "judged",
             "chronic_audit": "chronic", "operator_window": "op-window", "transient": "transient", "": "-"}


def _age_hours(first_miss_at: str, as_of: datetime) -> float | None:
    if not first_miss_at:
        return None
    try:
        t = datetime.fromisoformat(first_miss_at.replace("Z", "+00:00"))
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        return (as_of - t).total_seconds() / 3600.0
    except ValueError:
        return None


def pending_slot(row: dict[str, Any], as_of: datetime) -> int | None:
    """The next unfilled slot whose F-hour the open item's age has crossed (↑)."""
    age = _age_hours(str(row.get("first_miss_at") or ""), as_of)
    if age is None or row.get("resolved_at"):
        return None
    filled = {int(s["slot"]) for s in row.get("slots", []) if s.get("state")}
    for k in range(1, 10):
        if k in filled:
            continue
        if age >= FIB_HOURS[k] and (k - 1) in filled or (k == 1 and age >= 1):
            return k
        break
    return None


def render_backlog(rows: list[dict[str, Any]], *, as_of: datetime | None = None, filled_at: str = "", supervisor_connected: bool | None = None) -> str:
    as_of = as_of or datetime.now(timezone.utc)
    header = f"{'workflow / item':<40} {'cat':<9} " + " ".join(f"{h:>3}" for h in FIB_HOURS) + "   level"
    lines = [header, "-" * len(header)]
    for r in sorted(rows, key=lambda r: (-int(r.get("escalation_level") or 0), str(r.get("item_key") or r.get("workflow")))):
        cells = {int(s["slot"]): str(s.get("state") or "") for s in r.get("slots", [])}
        up = pending_slot(r, as_of)
        glyphs = []
        for k in range(10):
            g = GLYPH.get(cells.get(k, ""), "?")
            if g == "·" and up == k:
                g = "↑"
            glyphs.append(f"{g:>3}")
        level = int(r.get("escalation_level") or 0)
        tail = f"L{level} {r.get('channel') or ''}".strip() if level else ""
        if r.get("resolved_at") and any(cells.get(k) not in ("", "ok") for k in range(1, 10)):
            tail = (tail + " resolved").strip()
        name = str(r.get("item_key") or r.get("workflow"))
        lines.append(f"{name[:40]:<40} {CAT_SHORT.get(str(r.get('category') or ''), str(r.get('category') or ''))[:9]:<9} " + " ".join(glyphs) + (f"   {tail}" if tail else ""))
    if not rows:
        lines.append("(no backlog rows in the window — Nautilus has not filled, or the FDW view is absent)")
    foot = []
    if filled_at:
        foot.append(f"last fill {filled_at}")
    if supervisor_connected is not None:
        foot.append("supervisor connected" if supervisor_connected else "supervisor NOT connected")
    if foot:
        lines.append("")
        lines.append(" · ".join(foot))
    return "\n".join(lines)
