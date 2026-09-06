"""Text rendering for /activities (pure; no I/O).

One line per coordination Activity: state glyph, kind, who declared it, the
horizon, what it precludes, and which of OUR endpoints it holds.
"""

from __future__ import annotations

from typing import Any

_GLYPH = {
    "queued": "◌",
    "running": "●",
    "released": "○",
    "expired": "◍",
    "failed": "✗",
    "superseded": "↻",
}


def render_activities(
    rows: list[dict[str, Any]],
    *,
    watcher_connected: bool | None = None,
    signals_target: str = "",
    last_event_at: str = "",
) -> str:
    head = "coordination activities"
    if watcher_connected is True:
        head += f" · watching {signals_target}"
    elif watcher_connected is False:
        head += f" · NOT connected to {signals_target}" + (f" (last event {last_event_at})" if last_event_at else "")
    lines = [head]
    if not rows:
        lines.append("  (none in force)")
        return "\n".join(lines)
    for r in rows:
        state = str(r.get("state") or "")
        g = _GLYPH.get(state, "?")
        who = f"{r.get('peer') or '?'}:{r.get('owner') or '?'}"
        horizon = r.get("horizon_at") or "-"
        line = f"  {g} {state:<10} {r.get('kind') or '?':<20} {who:<28} until {horizon}"
        lines.append(line)
        detail: list[str] = []
        if r.get("ceded"):
            detail.append("holds " + ", ".join(r["ceded"]))
        if r.get("precludes"):
            detail.append("precludes " + ", ".join(r["precludes"]))
        if r.get("claims"):
            detail.append("claims " + ", ".join(r["claims"]))
        if r.get("reason"):
            detail.append(f"— {r['reason']}")
        if detail:
            lines.append("      " + "; ".join(detail))
        if r.get("note"):
            lines.append(f"      note: {r['note']}")
    return "\n".join(lines)
