"""Summary SCHEDULE catalog: live pg_cron clocks that enqueue scheduled_tasks.

Airflow schedules Metaflow when Airflow is available; pg_cron otherwise.
This catalog lists what is actually scheduled. Trigger = INSERT scheduled_tasks.
Do not invent DAG names.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

GURU_NOSCHED = (
    "Could not read the schedule catalog (cron.job).\n"
    "  Guru: #WS.00000010.NOSCHED\n"
    "  Try: /health fix postgres"
)
GURU_NOTRIG = (
    "That clock does not enqueue scheduled_tasks (or is unknown).\n"
    "  Guru: #WS.00000011.NOTRIG\n"
    "  Try: /summary schedules"
)

TASK_TYPE = re.compile(
    r"INSERT\s+INTO\s+scheduled_tasks.*?VALUES\s*\(\s*'([a-z][a-z0-9_]*)'",
    re.I | re.S,
)
TASK_TYPE_SELECT = re.compile(
    r"INSERT\s+INTO\s+scheduled_tasks.*?SELECT\s+'([a-z][a-z0-9_]*)'",
    re.I | re.S,
)


class ScheduleCatalogError(RuntimeError):
    """Fail-fast schedule catalog error."""


CADENCES = ("hourly", "daily", "weekly", "extended")


@dataclass(frozen=True)
class ScheduleCard:
    id: str
    cron: str
    task_type: str
    source: str
    enabled: bool
    triggerable: bool
    cadence: str = "extended"

    def as_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "cron": self.cron,
            "task_type": self.task_type,
            "source": self.source,
            "enabled": self.enabled,
            "triggerable": self.triggerable,
            "cadence": self.cadence,
        }


def _cron_field(field: str) -> str:
    raw = (field or "").strip()
    if raw in ("*", "?"):
        return "any"
    if raw.startswith("*/"):
        return "step"
    if "," in raw:
        return "list"
    if "-" in raw:
        return "range"
    return "atom"


def classify_cadence(cron: str) -> str:
    """hourly | daily | weekly | extended (month/quarter/year/fortnight)."""
    parts = (cron or "").split()
    if len(parts) < 5:
        return "extended"
    _minute, hour, dom, month, dow = parts[:5]
    if _cron_field(month) != "any":
        return "extended"
    if _cron_field(dom) != "any":
        return "extended"
    dow_k = _cron_field(dow)
    if dow_k == "list":
        return "extended"
    if dow_k in ("atom", "range"):
        return "weekly"
    hour_k = _cron_field(hour)
    if hour_k in ("any", "step"):
        return "hourly"
    if hour_k == "list" and hour.count(",") >= 2:
        return "hourly"
    return "daily"


def parse_task_type(command: str) -> str:
    raw = command or ""
    m = TASK_TYPE.search(raw) or TASK_TYPE_SELECT.search(raw)
    return m.group(1) if m else ""


async def list_schedule_catalog(db_pool: object | None) -> list[ScheduleCard]:
    if db_pool is None:
        raise ScheduleCatalogError(GURU_NOSCHED)
    try:
        async with db_pool.acquire() as conn:  # type: ignore[union-attr]
            rows = await conn.fetch(
                """
                SELECT jobname, schedule, command, active
                FROM cron.job
                ORDER BY jobname
                """
            )
    except Exception as e:
        raise ScheduleCatalogError(f"{GURU_NOSCHED}\n  Error: {e}") from e
    out: list[ScheduleCard] = []
    for row in rows:
        task = parse_task_type(row["command"] or "")
        if not task:
            continue
        expr = row["schedule"] or ""
        out.append(
            ScheduleCard(
                id=row["jobname"] or task,
                cron=expr,
                task_type=task,
                source="pg_cron",
                enabled=bool(row["active"]),
                triggerable=True,
                cadence=classify_cadence(expr),
            )
        )
    return out


async def trigger_schedule(
    db_pool: object | None,
    job_id: str,
    catalog: list[ScheduleCard] | None = None,
) -> tuple[int, str]:
    if db_pool is None:
        raise ScheduleCatalogError(GURU_NOSCHED)
    wanted = (job_id or "").strip()
    if not wanted:
        raise ScheduleCatalogError(GURU_NOTRIG)
    cards = catalog if catalog is not None else await list_schedule_catalog(db_pool)
    match = next((c for c in cards if c.id == wanted or c.task_type == wanted), None)
    if match is None or not match.triggerable or not match.task_type:
        raise ScheduleCatalogError(GURU_NOTRIG)
    try:
        async with db_pool.acquire() as conn:  # type: ignore[union-attr]
            row = await conn.fetchrow(
                """
                INSERT INTO scheduled_tasks (task_type, payload, source, scheduled_for)
                SELECT $1, '{}'::jsonb, 'summary-lineup', NOW()
                WHERE NOT EXISTS (
                    SELECT 1 FROM scheduled_tasks
                    WHERE task_type = $1
                      AND picked_up_at IS NULL
                      AND completed_at IS NULL
                )
                RETURNING id
                """,
                match.task_type,
            )
            if row is None:
                existing = await conn.fetchval(
                    """
                    SELECT id FROM scheduled_tasks
                    WHERE task_type = $1
                      AND picked_up_at IS NULL
                      AND completed_at IS NULL
                    ORDER BY id DESC
                    LIMIT 1
                    """,
                    match.task_type,
                )
                return int(existing or 0), match.task_type
            return int(row["id"]), match.task_type
    except ScheduleCatalogError:
        raise
    except Exception as e:
        raise ScheduleCatalogError(f"{GURU_NOSCHED}\n  Error: {e}") from e
