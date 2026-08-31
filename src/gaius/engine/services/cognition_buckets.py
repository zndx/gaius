"""Scale-aware bucketing for the Cognition surface (pure — no I/O).

Ported from wxs-agentsview ``internal/activity/query.go`` (MIT) and adapted
for sparse thought cadence; the window grammar follows the in-repo
``discover_surface.parse_window`` convention. All tiling is UTC — the page
is explicitly UTC-labeled.

Three-tier contract (AgentsView): the SERVER resolves the bucket unit from
the range duration and returns real half-open bucket bounds; the client
positions each bucket by its actual bounds; axis strategies switch on the
unit. Unlike upstream, an over-budget range DEGRADES resolution instead of
failing.
"""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

GURU_BADBUCKET = (
    "CognitionSurface bucket must be one of hour|6h|day|week|month.\n"
    "  Guru: #COG.00000032.BADBUCKET"
)
GURU_BADRANGE = (
    "CognitionSurface from_ms/to_ms must both be set, with from < to.\n"
    "  Guru: #COG.00000033.BADRANGE"
)
GURU_BADWINDOWSTR = (
    "CognitionSurface window must be like 24h, 7d, 30d, 365d, or all.\n"
    "  Guru: #COG.00000034.BADWINDOWSTR"
)

MAX_BUCKETS = 2000
MAX_WINDOW = timedelta(days=3660)
MIN_WINDOW = timedelta(hours=1)

# Nominal seconds per unit (month is nominal; real month buckets vary).
BUCKET_SECONDS = {
    "hour": 3600,
    "6h": 21600,
    "day": 86400,
    "week": 604800,
    "month": 2629800,
}
_UNIT_ORDER = ("hour", "6h", "day", "week", "month")


@dataclass(frozen=True)
class BucketWindow:
    """Half-open [start, end) UTC window."""

    start: datetime
    end: datetime


def _utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_window(window: str) -> timedelta | None:
    """``24h`` / ``7d`` / ``365d`` / ``all`` → timedelta (None = all history)."""
    w = (window or "").strip().lower()
    if not w:
        raise ValueError(GURU_BADWINDOWSTR)
    if w == "all":
        return None
    try:
        if w.endswith("h"):
            delta = timedelta(hours=int(w[:-1]))
        elif w.endswith("d"):
            delta = timedelta(days=int(w[:-1]))
        else:
            raise ValueError(GURU_BADWINDOWSTR)
    except ValueError as e:
        raise ValueError(GURU_BADWINDOWSTR) from e
    if delta < MIN_WINDOW or delta > MAX_WINDOW:
        raise ValueError(GURU_BADWINDOWSTR)
    return delta


def resolve_range(
    now: datetime,
    *,
    window_days: int = 0,
    window: str = "",
    from_ms: int = 0,
    to_ms: int = 0,
    oldest: datetime | None = None,
) -> tuple[datetime, datetime]:
    """Resolve the [start, end) range. Precedence: from/to > window > window_days.

    ``window="all"`` starts at ``oldest`` (or 365d back when unknown/empty).
    """
    now = _utc(now)
    if from_ms or to_ms:
        if not (from_ms and to_ms) or from_ms >= to_ms:
            raise ValueError(GURU_BADRANGE)
        start = datetime.fromtimestamp(from_ms / 1000.0, tz=timezone.utc)
        end = datetime.fromtimestamp(to_ms / 1000.0, tz=timezone.utc)
        if end - start > MAX_WINDOW:
            raise ValueError(GURU_BADRANGE)
        return start, end
    if window:
        delta = parse_window(window)
        if delta is None:  # all history
            start = _utc(oldest) if oldest is not None else now - timedelta(days=365)
            if start >= now:
                start = now - MIN_WINDOW
            if now - start > MAX_WINDOW:
                start = now - MAX_WINDOW
            return start, now
        return now - delta, now
    days = int(window_days or 365)
    if days < 1 or days > 3660:
        # kept in cognition_surface.normalize_window's guru for back-compat
        raise ValueError(GURU_BADWINDOWSTR)
    return now - timedelta(days=days), now


def _estimate_count(start: datetime, end: datetime, unit: str) -> int:
    span = (end - start).total_seconds()
    return int(span // BUCKET_SECONDS[unit]) + 1


def resolve_bucket(start: datetime, end: datetime, override: str = "") -> str:
    """Pick a bucket unit for [start, end).

    Empty override applies the duration-based auto policy (tuned for sparse
    thought cadence); otherwise the allow-list is consulted. Either way, a
    range that would exceed MAX_BUCKETS degrades to a coarser unit — the
    response's echoed interval is the truth the client renders.
    """
    start, end = _utc(start), _utc(end)
    if override:
        if override not in BUCKET_SECONDS:
            raise ValueError(GURU_BADBUCKET)
        unit = override
    else:
        d = end - start
        if d <= timedelta(hours=48):
            unit = "hour"
        elif d <= timedelta(days=14):
            unit = "6h"
        elif d <= timedelta(days=180):
            unit = "day"
        elif d <= timedelta(days=1100):
            unit = "week"
        else:
            unit = "month"
    while _estimate_count(start, end, unit) > MAX_BUCKETS:
        idx = _UNIT_ORDER.index(unit)
        if idx == len(_UNIT_ORDER) - 1:
            break
        unit = _UNIT_ORDER[idx + 1]
    return unit


def _utc_midnight(dt: datetime) -> datetime:
    dt = _utc(dt)
    return dt.replace(hour=0, minute=0, second=0, microsecond=0)


def _iso_monday(dt: datetime) -> datetime:
    mid = _utc_midnight(dt)
    return mid - timedelta(days=mid.weekday())


def _month_first(dt: datetime) -> datetime:
    mid = _utc_midnight(dt)
    return mid.replace(day=1)


def _next_month(dt: datetime) -> datetime:
    if dt.month == 12:
        return dt.replace(year=dt.year + 1, month=1)
    return dt.replace(month=dt.month + 1)


def build_buckets(start: datetime, end: datetime, unit: str) -> list[BucketWindow]:
    """Tile [start, end) into half-open UTC windows for the unit.

    hour/6h are fixed-duration anchored at start (last window clipped);
    day/week/month follow UTC calendar boundaries (ISO Monday for weeks,
    the 1st for months) with the first/last windows clipped to the range.
    """
    start, end = _utc(start), _utc(end)
    if start >= end:
        return []

    if unit in ("hour", "6h"):
        step = timedelta(seconds=BUCKET_SECONDS[unit])
        out: list[BucketWindow] = []
        cursor = start
        while cursor < end:
            out.append(BucketWindow(cursor, min(cursor + step, end)))
            cursor += step
        return out

    if unit == "day":
        anchor, advance = _utc_midnight(start), lambda d: d + timedelta(days=1)
    elif unit == "week":
        anchor, advance = _iso_monday(start), lambda d: d + timedelta(days=7)
    elif unit == "month":
        anchor, advance = _month_first(start), _next_month
    else:
        raise ValueError(GURU_BADBUCKET)

    out = []
    cursor = anchor
    while cursor < end:
        nxt = advance(cursor)
        b_start = max(cursor, start)
        b_end = min(nxt, end)
        if b_end > b_start:
            out.append(BucketWindow(b_start, b_end))
        cursor = nxt
    return out


def bucket_index(buckets: list[BucketWindow], ts: datetime) -> int:
    """Index of the bucket containing ts, or -1. Bisect on starts."""
    ts = _utc(ts)
    starts = [b.start for b in buckets]
    i = bisect_right(starts, ts) - 1
    if i < 0:
        return -1
    if ts >= buckets[i].end:
        return -1
    return i


def fold_rows(
    buckets: list[BucketWindow],
    rows: list[tuple[datetime, dict[str, float]]],
) -> list[dict[str, float]]:
    """Fold (timestamp, values) rows into per-bucket sums (zero-filled)."""
    acc: list[dict[str, float]] = [dict() for _ in buckets]
    starts = [b.start for b in buckets]
    for ts, values in rows:
        ts = _utc(ts)
        i = bisect_right(starts, ts) - 1
        if i < 0 or ts >= buckets[i].end:
            continue
        slot = acc[i]
        for key, val in values.items():
            if key.endswith("_max"):
                slot[key] = max(slot.get(key, 0.0), val)
            else:
                slot[key] = slot.get(key, 0.0) + val
    return acc


def fold_named_series(
    buckets: list[BucketWindow],
    rows: list[tuple[datetime, str, int]],
) -> dict[str, list[int]]:
    """Fold (timestamp, name, count) rows into per-name zero-filled int
    series positionally aligned with ``buckets``. Out-of-range rows drop."""
    starts = [b.start for b in buckets]
    out: dict[str, list[int]] = {}
    for ts, name, n in rows:
        ts = _utc(ts)
        i = bisect_right(starts, ts) - 1
        if i < 0 or ts >= buckets[i].end:
            continue
        series = out.setdefault(name, [0] * len(buckets))
        series[i] += int(n)
    return out
