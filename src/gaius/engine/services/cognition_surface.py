"""Federation cognition surface — honest window aggregates.

Gaius-ui /cognition is this unit's AgentsView-shaped attention
dashboard. Streams are thought types (pattern, connection, …),
not Claude/Codex coding sessions. Empty windows are zeros, not
invented warehouses.

SQL lives here so the servicer stays a thin gRPC map.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from gaius.engine.services.cognition_buffer import NEXT_QUESTION_RESERVE_TOKENS

SURFACE_GURU_NODB = (
    "Cognition surface needs the engine database pool.\n"
    "  Guru: #COG.00000025.NODB\n"
    "  Try: /health fix postgres"
)
SURFACE_GURU_WINDOW = (
    "CognitionSurface window_days must be in 1..3660.\n"
    "  Guru: #COG.00000026.BADWINDOW"
)
SURFACE_GURU_LIMIT = (
    "CognitionSurface thought_limit must be in 1..200.\n"
    "  Guru: #COG.00000027.BADLIMIT"
)


@dataclass
class SurfaceThought:
    id: str
    thought_type: str
    title: str
    summary: str
    salience: float
    generation: int
    timestamp_ms: int
    note_path: str


@dataclass
class SurfaceDay:
    date: str
    thoughts: int
    cycles: int


@dataclass
class SurfaceHour:
    weekday: int
    hour: int
    thoughts: int


@dataclass
class SurfaceStream:
    id: str
    thoughts: int


@dataclass
class CognitionSurface:
    running: bool
    cycles_completed: int
    cycles_in_window: int
    last_cycle_timestamp_ms: int
    current_task: str
    thoughts: int
    streams: int
    active_days: int
    thoughts_per_cycle: float
    concentration_stream: str
    concentration_pct: float
    reserve_tokens: int
    project: str
    unit: str
    recent: list[SurfaceThought] = field(default_factory=list)
    top: list[SurfaceThought] = field(default_factory=list)
    days: list[SurfaceDay] = field(default_factory=list)
    hours: list[SurfaceHour] = field(default_factory=list)
    stream_counts: list[SurfaceStream] = field(default_factory=list)
    error: str = ""


def normalize_window(window_days: int) -> int:
    days = int(window_days or 365)
    if days < 1 or days > 3660:
        raise ValueError(SURFACE_GURU_WINDOW)
    return days


def normalize_limit(thought_limit: int) -> int:
    limit = int(thought_limit or 80)
    if limit < 1 or limit > 200:
        raise ValueError(SURFACE_GURU_LIMIT)
    return limit


def concentration(stream_counts: list[tuple[str, int]]) -> tuple[str, float]:
    """Dominant stream id and percent of window thoughts."""
    total = sum(n for _, n in stream_counts)
    if total <= 0 or not stream_counts:
        return "", 0.0
    top_id, top_n = max(stream_counts, key=lambda item: item[1])
    return top_id, (100.0 * top_n) / total


def thoughts_per_cycle(thoughts: int, cycles: int) -> float:
    if cycles <= 0:
        return 0.0
    return thoughts / cycles


def _ts_ms(value: datetime | None) -> int:
    if value is None:
        return 0
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return int(value.timestamp() * 1000)


def _row_thought(row: Any) -> SurfaceThought:
    summary = row["summary"] or ""
    if not summary:
        content = row.get("content") or ""
        summary = content[:160]
    gen = row.get("generation")
    return SurfaceThought(
        id=str(row["id"]),
        thought_type=row["thought_type"] or "",
        title=row["title"] or "",
        summary=summary,
        salience=float(row["salience"] or 0.0),
        generation=int(gen or 0),
        timestamp_ms=_ts_ms(row["created_at"]),
        note_path=row.get("note_path") or "",
    )


async def build_cognition_surface(
    db_pool: Any,
    *,
    window_days: int,
    thought_limit: int,
    stream: str,
    status: dict[str, Any],
) -> CognitionSurface:
    """Query the window. Fail-fast if the pool is missing."""
    if db_pool is None:
        raise RuntimeError(SURFACE_GURU_NODB)
    days = normalize_window(window_days)
    limit = normalize_limit(thought_limit)
    stream_id = (stream or "").strip()

    last_cycle_ms = 0
    last_cycle_at = status.get("last_cycle_at")
    if last_cycle_at:
        if isinstance(last_cycle_at, datetime):
            last_cycle_ms = _ts_ms(last_cycle_at)
        else:
            try:
                parsed = datetime.fromisoformat(str(last_cycle_at))
                last_cycle_ms = _ts_ms(parsed)
            except ValueError:
                last_cycle_ms = 0

    async with db_pool.acquire() as conn:
        totals = await conn.fetchrow(
            """
            SELECT
              COUNT(*)::int AS thoughts,
              COUNT(DISTINCT thought_type)::int AS streams,
              COUNT(DISTINCT (created_at AT TIME ZONE 'UTC')::date)::int AS active_days
            FROM cognition_thoughts
            WHERE created_at >= NOW() - ($1::int * INTERVAL '1 day')
              AND ($2 = '' OR thought_type = $2)
            """,
            days,
            stream_id,
        )
        cycle_row = await conn.fetchrow(
            """
            SELECT COUNT(*)::int AS cycles
            FROM cognition_cycles
            WHERE started_at >= NOW() - ($1::int * INTERVAL '1 day')
            """,
            days,
        )
        type_rows = await conn.fetch(
            """
            SELECT thought_type, COUNT(*)::int AS n
            FROM cognition_thoughts
            WHERE created_at >= NOW() - ($1::int * INTERVAL '1 day')
            GROUP BY thought_type
            ORDER BY n DESC, thought_type
            """,
            days,
        )
        day_thought_rows = await conn.fetch(
            """
            SELECT (created_at AT TIME ZONE 'UTC')::date AS d, COUNT(*)::int AS n
            FROM cognition_thoughts
            WHERE created_at >= NOW() - ($1::int * INTERVAL '1 day')
              AND ($2 = '' OR thought_type = $2)
            GROUP BY 1
            ORDER BY 1
            """,
            days,
            stream_id,
        )
        day_cycle_rows = await conn.fetch(
            """
            SELECT (started_at AT TIME ZONE 'UTC')::date AS d, COUNT(*)::int AS n
            FROM cognition_cycles
            WHERE started_at >= NOW() - ($1::int * INTERVAL '1 day')
            GROUP BY 1
            ORDER BY 1
            """,
            days,
        )
        hour_rows = await conn.fetch(
            """
            SELECT
              EXTRACT(DOW FROM created_at AT TIME ZONE 'UTC')::int AS weekday,
              EXTRACT(HOUR FROM created_at AT TIME ZONE 'UTC')::int AS hour,
              COUNT(*)::int AS n
            FROM cognition_thoughts
            WHERE created_at >= NOW() - ($1::int * INTERVAL '1 day')
              AND ($2 = '' OR thought_type = $2)
            GROUP BY 1, 2
            """,
            days,
            stream_id,
        )
        recent_rows = await conn.fetch(
            """
            SELECT id, thought_type, title, summary, content,
                   salience, generation, note_path, created_at
            FROM cognition_thoughts
            WHERE created_at >= NOW() - ($1::int * INTERVAL '1 day')
              AND ($2 = '' OR thought_type = $2)
            ORDER BY created_at DESC
            LIMIT $3
            """,
            days,
            stream_id,
            limit,
        )
        top_rows = await conn.fetch(
            """
            SELECT id, thought_type, title, summary, content,
                   salience, generation, note_path, created_at
            FROM cognition_thoughts
            WHERE created_at >= NOW() - ($1::int * INTERVAL '1 day')
              AND ($2 = '' OR thought_type = $2)
            ORDER BY salience DESC, created_at DESC
            LIMIT 10
            """,
            days,
            stream_id,
        )

    thoughts = int(totals["thoughts"] if totals else 0)
    streams = int(totals["streams"] if totals else 0)
    active_days = int(totals["active_days"] if totals else 0)
    cycles_in_window = int(cycle_row["cycles"] if cycle_row else 0)
    stream_pairs = [
        (str(r["thought_type"] or ""), int(r["n"])) for r in type_rows
    ]
    conc_id, conc_pct = concentration(stream_pairs)

    cycle_by_day = {str(r["d"]): int(r["n"]) for r in day_cycle_rows}
    day_map: dict[str, SurfaceDay] = {}
    for r in day_thought_rows:
        key = str(r["d"])
        day_map[key] = SurfaceDay(
            date=key, thoughts=int(r["n"]), cycles=cycle_by_day.get(key, 0)
        )
    for key, n in cycle_by_day.items():
        if key not in day_map:
            day_map[key] = SurfaceDay(date=key, thoughts=0, cycles=n)

    return CognitionSurface(
        running=bool(status.get("running", False)),
        cycles_completed=int(status.get("cycles_completed") or 0),
        cycles_in_window=cycles_in_window,
        last_cycle_timestamp_ms=last_cycle_ms,
        current_task=str(status.get("current_task") or ""),
        thoughts=thoughts,
        streams=streams,
        active_days=active_days,
        thoughts_per_cycle=thoughts_per_cycle(thoughts, cycles_in_window),
        concentration_stream=conc_id,
        concentration_pct=conc_pct,
        reserve_tokens=NEXT_QUESTION_RESERVE_TOKENS,
        project="gaius",
        unit="cognition",
        recent=[_row_thought(r) for r in recent_rows],
        top=[_row_thought(r) for r in top_rows],
        days=sorted(day_map.values(), key=lambda d: d.date),
        hours=[
            SurfaceHour(
                weekday=int(r["weekday"]),
                hour=int(r["hour"]),
                thoughts=int(r["n"]),
            )
            for r in hour_rows
        ],
        stream_counts=[SurfaceStream(id=i, thoughts=n) for i, n in stream_pairs],
    )
