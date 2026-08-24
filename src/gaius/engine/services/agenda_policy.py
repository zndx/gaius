"""Cognition agenda densities and copy-paste session invites.

Kinds:
- session: a few times a week, Aperture-world-events, calendar description
- reminder: short follow-up lists (content, ops, discretionary)
- brief: regular expert-technical executive notes; keep operational specifics

Guru: #COG.00000033.AGENDADENSE
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

GURU = (
    "Agenda density or invite formatting failed.\n"
    "  Guru: #COG.00000033.AGENDADENSE"
)


@dataclass(frozen=True)
class AgendaDensity:
    """Per-kind targets over a rolling week of *open* entries."""

    sessions_per_week: int = 3
    briefs_per_week: int = 5
    reminders_open_max: int = 8
    reminder_items_max: int = 5
    window_days: int = 7


DEFAULT_DENSITY = AgendaDensity()


def slots_remaining(
    open_counts: dict[str, int],
    density: AgendaDensity = DEFAULT_DENSITY,
) -> dict[str, int]:
    """How many new rows of each kind Cognition may add this cycle."""
    return {
        "session": max(0, density.sessions_per_week - int(open_counts.get("session", 0))),
        "brief": max(0, density.briefs_per_week - int(open_counts.get("brief", 0))),
        "reminder": max(
            0, density.reminders_open_max - int(open_counts.get("reminder", 0))
        ),
    }


def take_kind(
    items: list[dict[str, Any]],
    *,
    kind: str,
    slots: int,
    reminder_items_max: int = 5,
) -> list[dict[str, Any]]:
    if slots <= 0:
        return []
    if kind == "reminder":
        out = []
        for item in items[:slots]:
            clipped = dict(item)
            clipped["body"] = clip_reminder_list(
                str(item.get("body") or ""), reminder_items_max
            )
            out.append(clipped)
        return out
    return items[:slots]


def clip_reminder_list(body: str, max_items: int) -> str:
    lines = [ln.strip() for ln in body.splitlines() if ln.strip()]
    bullets: list[str] = []
    for ln in lines:
        if ln.startswith(("-", "*", "•")):
            bullets.append(ln.lstrip("-*• ").strip())
        else:
            bullets.extend(p.strip() for p in ln.split(";") if p.strip())
    if not bullets and body.strip():
        bullets = [body.strip()]
    bullets = bullets[:max_items]
    return "\n".join(f"- {b}" for b in bullets)


def next_session_slots(
    now: datetime,
    existing: list[datetime],
    *,
    per_week: int = 3,
) -> list[datetime]:
    """Spread remaining sessions across the coming week (not daily)."""
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    week_end = now + timedelta(days=7)
    taken = {d.date() for d in existing if now <= d <= week_end}
    preferred = []
    # A few times a week: Tue / Thu / Sat relative to `now`
    for offset in (1, 3, 5, 2, 4, 6):
        day = (now + timedelta(days=offset)).replace(
            hour=16, minute=0, second=0, microsecond=0
        )
        if day.date() not in taken:
            preferred.append(day)
        if len(preferred) >= per_week:
            break
    return preferred


def session_invite_description(
    *,
    title: str,
    body: str,
    episode_id: str,
    hx_generation_id: str,
    due_at: datetime | None = None,
) -> str:
    """Calendar invite description; paste into Gaius Terminal to begin."""
    when = due_at.isoformat() if due_at else "unscheduled"
    return (
        f"Gaius Aperture session — world events through unique MaxSim topics\n"
        f"{title.strip()}\n\n"
        f"{body.strip()}\n\n"
        f"When: {when}\n"
        f"Episode: {episode_id}\n"
        f"HX: {hx_generation_id}\n\n"
        f"--- paste into Gaius Terminal to begin ---\n"
        f"BEGIN SESSION\n"
        f"episode={episode_id}\n"
        f"hx={hx_generation_id}\n"
        f"{title.strip()}\n"
        f"END SESSION\n"
    )


def brief_keeps_operations(body: str) -> bool:
    """Executive briefs must not strip guru codes, DROP RANGE, or FDW."""
    return True  # formatting is additive; never redact
