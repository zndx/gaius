"""Discover landing snapshot — inflow events as Activation Examples.

P0 reads ``content_items`` (last window). Feature pins with no tape
return an empty document set (honest). SQL stays here; the servicer
is a thin gRPC map.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

GURU_NODB = (
    "Discover surface needs the engine database pool.\n"
    "  Guru: #DI.00000001.NODB\n"
    "  Try: /health fix postgres"
)
GURU_WINDOW = (
    "Discover window must be like 36h, 7d, or 1h (1..3660 days).\n"
    "  Guru: #DI.00000002.BADWINDOW"
)
GURU_LIMIT = (
    "Discover limit must be in 1..200.\n"
    "  Guru: #DI.00000003.BADLIMIT"
)
GURU_BREAKDOWN = (
    "Discover breakdown must be stream, source, or layer.\n"
    "  Guru: #DI.00000004.BADBREAK"
)

_WINDOW_RE = re.compile(r"^(\d+)([mhd])$")
_FEATURE_RE = re.compile(r"^(\d+):(\d+)$")
_KV_RE = re.compile(r"^(stream|source|feature):(\S+)$", re.I)


class DiscoverError(ValueError):
    """Fail-fast Discover argument / pool error."""


@dataclass
class DiscoverQuery:
    stream: str = ""
    source: str = ""
    features: list[tuple[int, int]] = field(default_factory=list)
    text: str = ""


@dataclass
class DiscoverBucket:
    t: str
    n: int
    breakdown_key: str = ""
    salience: float = 0.0
    watts: float = 0.0
    util: float = 0.0
    salience_ma: float = 0.0
    watts_ma: float = 0.0
    util_ma: float = 0.0


@dataclass
class DiscoverEpisode:
    kind: str
    at: str
    eta_s: int
    label: str


@dataclass
class DiscoverDoc:
    id: str
    stream: str
    source: str
    ts: str
    title: str
    body: str
    source_id: str
    url: str


@dataclass
class DiscoverFacet:
    key: str
    kind: str
    count: int
    salience: float = 0.0


@dataclass
class DiscoverSurface:
    buckets: list[DiscoverBucket]
    docs: list[DiscoverDoc]
    facets: list[DiscoverFacet]
    total: int
    window: str
    query: str
    scraped_at: str
    interval: str
    last_salience_at: str = ""
    next_episode: DiscoverEpisode | None = None
    clock: str = "wall"


def parse_window(raw: str) -> timedelta:
    token = (raw or "36h").strip().lower()
    m = _WINDOW_RE.match(token)
    if not m:
        raise DiscoverError(GURU_WINDOW)
    n = int(m.group(1))
    unit = m.group(2)
    if n < 1:
        raise DiscoverError(GURU_WINDOW)
    if unit == "m":
        delta = timedelta(minutes=n)
    elif unit == "h":
        delta = timedelta(hours=n)
    else:
        delta = timedelta(days=n)
    if delta > timedelta(days=3660):
        raise DiscoverError(GURU_WINDOW)
    return delta


def parse_query(raw: str, feature_pins: list[str] | None = None) -> DiscoverQuery:
    q = DiscoverQuery()
    leftover: list[str] = []
    for tok in (raw or "").split():
        m = _KV_RE.match(tok)
        if not m:
            leftover.append(tok)
            continue
        kind, val = m.group(1).lower(), m.group(2)
        if kind == "stream":
            q.stream = val
        elif kind == "source":
            q.source = val
        else:
            fm = _FEATURE_RE.match(val)
            if not fm:
                raise DiscoverError(
                    f"feature pin must be layer:index (got {val!r}).\n"
                    "  Guru: #DI.00000005.BADFEATURE"
                )
            q.features.append((int(fm.group(1)), int(fm.group(2))))
    for pin in feature_pins or []:
        fm = _FEATURE_RE.match((pin or "").strip())
        if not fm:
            raise DiscoverError(
                f"feature pin must be layer:index (got {pin!r}).\n"
                "  Guru: #DI.00000005.BADFEATURE"
            )
        q.features.append((int(fm.group(1)), int(fm.group(2))))
    q.text = " ".join(leftover).strip()
    return q


def auto_interval(delta: timedelta) -> str:
    """PostgreSQL date_trunc field: minute | hour | day."""
    secs = delta.total_seconds()
    if secs <= 2 * 3600:
        return "minute"
    if secs <= 7 * 24 * 3600:
        return "hour"
    return "day"


def _iso(ts: datetime | None) -> str:
    if ts is None:
        return ""
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc).isoformat()


def rolling_ma(vals: list[float], k: int = 5) -> list[float]:
    """Simple k-minute trailing mean. TUI Observe uses sparklines; this is the landing analog."""
    out: list[float] = []
    for i in range(len(vals)):
        sl = vals[max(0, i - k + 1) : i + 1]
        out.append(sum(sl) / len(sl) if sl else 0.0)
    return out


def next_cron(now: datetime, minute_expr: str, hour_expr: str) -> datetime:
    """Next fire for a 5-field cron we actually schedule (minute + hour only)."""
    minutes = _cron_field(minute_expr, 0, 59)
    hours = _cron_field(hour_expr, 0, 23)
    cursor = now.replace(second=0, microsecond=0) + timedelta(minutes=1)
    for _ in range(8 * 24 * 60):
        if cursor.minute in minutes and cursor.hour in hours:
            return cursor
        cursor += timedelta(minutes=1)
    raise DiscoverError(GURU_WINDOW)


def _cron_field(expr: str, lo: int, hi: int) -> set[int]:
    expr = (expr or "*").strip()
    if expr == "*":
        return set(range(lo, hi + 1))
    if expr.startswith("*/"):
        step = int(expr[2:])
        return set(range(lo, hi + 1, step))
    out: set[int] = set()
    for part in expr.split(","):
        out.add(int(part))
    return out


def _window_token(window: str) -> str:
    w = (window or "1h").strip().lower()
    if w in ("", "salience"):
        return "1h"
    return w


async def _last_salience_at(pool: Any) -> datetime | None:
    async with pool.acquire() as conn:
        ts = await conn.fetchval("SELECT max(created_at) FROM feature_tape")
    if ts is None:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts


async def _salience_window(
    pool: Any, now: datetime, delta: timedelta
) -> tuple[datetime, datetime, datetime | None]:
    last = await _last_salience_at(pool)
    if last is None:
        return now - delta, now, None
    # Live if we wrote in the last two minutes; else freeze at last accrual
    # so the landing shows tail-to-zero, not the empty chasm since then.
    end = now if (now - last) <= timedelta(minutes=2) else last
    return end - delta, end, last


async def next_salience_episode(pool: Any, now: datetime) -> DiscoverEpisode:
    """Soonest cron that can still produce salience (skip empty probe no-ops)."""
    async with pool.acquire() as conn:
        unprobed = int(
            await conn.fetchval(
                """
                SELECT count(*) FROM content_items c
                 WHERE c.fetched_at >= $1
                   AND NOT COALESCE(c.summary_excluded, false)
                   AND NOT EXISTS (
                       SELECT 1 FROM feature_tape t
                        WHERE t.event_id = 'inflow:' || c.id::text
                   )
                """,
                now - timedelta(days=7),
            )
            or 0
        )
        llm_pending = int(
            await conn.fetchval(
                """
                SELECT count(*) FROM content_items
                 WHERE llm_quality_score IS NULL
                   AND NOT COALESCE(summary_excluded, false)
                """
            )
            or 0
        )
        proc_pending = int(
            await conn.fetchval(
                """
                SELECT count(*) FROM content_items
                 WHERE processed_at IS NULL
                   AND llm_quality_score >= 50
                   AND NOT COALESCE(summary_excluded, false)
                """
            )
            or 0
        )

    candidates: list[DiscoverEpisode] = []
    if unprobed > 0:
        at = next_cron(now, "*/5", "*")
        candidates.append(
            DiscoverEpisode(
                kind="feature_probe",
                at=_iso(at),
                eta_s=max(0, int((at - now).total_seconds())),
                label=f"CLT probe ({unprobed} unprobed)",
            )
        )
    at = next_cron(now, "17", "*/4")
    candidates.append(
        DiscoverEpisode(
            kind="feed_check",
            at=_iso(at),
            eta_s=max(0, int((at - now).total_seconds())),
            label="Feed fetch (ArXiv / bioRxiv / blogs)",
        )
    )
    if llm_pending > 0:
        at = next_cron(now, "35", "0,4,8,12,16,20")
        candidates.append(
            DiscoverEpisode(
                kind="llm_triage",
                at=_iso(at),
                eta_s=max(0, int((at - now).total_seconds())),
                label=f"LLM triage ({llm_pending} waiting)",
            )
        )
    if proc_pending > 0:
        at = next_cron(now, "45", "*/2")
        candidates.append(
            DiscoverEpisode(
                kind="content_processing",
                at=_iso(at),
                eta_s=max(0, int((at - now).total_seconds())),
                label=f"KB file ({proc_pending} waiting)",
            )
        )
    at = next_cron(now, "43", "0,4,8,12,16,20")
    candidates.append(
        DiscoverEpisode(
            kind="cognition_cycle",
            at=_iso(at),
            eta_s=max(0, int((at - now).total_seconds())),
            label="Cognition cycle",
        )
    )
    return min(candidates, key=lambda e: e.eta_s)


def _grid_step(interval: str) -> timedelta:
    if interval == "minute":
        return timedelta(minutes=1)
    if interval == "hour":
        return timedelta(hours=1)
    return timedelta(days=1)


def _align(ts: datetime, interval: str) -> datetime:
    ts = ts.replace(second=0, microsecond=0)
    if interval == "hour":
        return ts.replace(minute=0)
    if interval == "day":
        return ts.replace(hour=0, minute=0)
    return ts


def _fill_minutes(
    start: datetime,
    end: datetime,
    sal_rows: list[Any],
    gpu_rows: list[Any],
    interval: str = "minute",
) -> list[DiscoverBucket]:
    sal_by: dict[datetime, tuple[int, float]] = {}
    for r in sal_rows:
        m = r["m"]
        if m.tzinfo is None:
            m = m.replace(tzinfo=timezone.utc)
        sal_by[m] = (int(r["n"]), float(r["sal"] or 0.0))
    gpu_by: dict[datetime, tuple[float, float]] = {}
    for r in gpu_rows:
        m = r["m"]
        if m.tzinfo is None:
            m = m.replace(tzinfo=timezone.utc)
        gpu_by[m] = (float(r["watts"] or 0.0), float(r["util"] or 0.0))

    start_m = _align(start, interval)
    end_m = _align(end, interval)
    step = _grid_step(interval)
    minutes: list[datetime] = []
    cur = start_m
    while cur <= end_m:
        minutes.append(cur)
        cur += step

    n_s, sal_s, w_s, u_s = [], [], [], []
    for m in minutes:
        n, sal = sal_by.get(m, (0, 0.0))
        w, u = gpu_by.get(m, (0.0, 0.0))
        n_s.append(n)
        sal_s.append(sal)
        w_s.append(w)
        u_s.append(u)
    sal_ma = rolling_ma(sal_s)
    w_ma = rolling_ma(w_s)
    u_ma = rolling_ma(u_s)
    return [
        DiscoverBucket(
            t=_iso(m),
            n=n_s[i],
            breakdown_key="",
            salience=sal_s[i],
            watts=w_s[i],
            util=u_s[i],
            salience_ma=sal_ma[i],
            watts_ma=w_ma[i],
            util_ma=u_ma[i],
        )
        for i, m in enumerate(minutes)
    ]


async def load_discover(
    db_pool: Any,
    *,
    window: str = "1h",
    query: str = "",
    breakdown: str = "source",
    limit: int = 50,
    feature_pins: list[str] | None = None,
    from_ts: str = "",
    to_ts: str = "",
) -> DiscoverSurface:
    if db_pool is None:
        raise DiscoverError(GURU_NODB)
    if limit < 1 or limit > 200:
        raise DiscoverError(GURU_LIMIT)
    br = (breakdown or "source").strip().lower()
    if br not in ("stream", "source", "layer"):
        raise DiscoverError(GURU_BREAKDOWN)

    parsed = parse_query(query, feature_pins)
    now = datetime.now(timezone.utc)
    clock = "wall"
    last_sal: datetime | None = None
    if from_ts.strip() and to_ts.strip():
        start = datetime.fromisoformat(from_ts.strip().replace("Z", "+00:00"))
        end = datetime.fromisoformat(to_ts.strip().replace("Z", "+00:00"))
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)
        delta = end - start
        if delta <= timedelta(0):
            raise DiscoverError(GURU_WINDOW)
        win_label = window or "custom"
        last_sal = await _last_salience_at(db_pool)
    else:
        win_label = _window_token(window)
        delta = parse_window(win_label)
        start, end, last_sal = await _salience_window(db_pool, now, delta)
        clock = "salience"

    interval = auto_interval(delta)
    scraped = now.isoformat()
    episode = await next_salience_episode(db_pool, now)

    if clock == "salience":
        where = [
            "NOT COALESCE(c.summary_excluded, false)",
            """EXISTS (
                 SELECT 1 FROM feature_tape t
                  WHERE t.event_id = 'inflow:' || c.id::text
                    AND t.created_at >= $1 AND t.created_at <= $2
               )""",
        ]
    else:
        where = [
            "c.fetched_at >= $1",
            "c.fetched_at < $2",
            "NOT COALESCE(c.summary_excluded, false)",
        ]
    args: list[Any] = [start, end]
    n = 2
    if parsed.stream and parsed.stream != "inflow":
        return DiscoverSurface(
            buckets=[],
            docs=[],
            facets=[],
            total=0,
            window=win_label,
            query=query or "",
            scraped_at=scraped,
            interval=interval,
            last_salience_at=_iso(last_sal),
            next_episode=episode,
            clock=clock,
        )
    if parsed.source:
        n += 1
        where.append(f"s.name = ${n}")
        args.append(parsed.source)
    if parsed.text:
        n += 1
        where.append(f"(c.title ILIKE ${n} OR COALESCE(c.summary, '') ILIKE ${n})")
        args.append(f"%{parsed.text}%")
    # Facets AND: every pinned feature must fire on the same document.
    seen: set[tuple[int, int]] = set()
    for layer, idx in parsed.features:
        if (layer, idx) in seen:
            continue
        seen.add((layer, idx))
        n += 1
        where.append(
            f"EXISTS (SELECT 1 FROM feature_tape t "
            f"WHERE t.event_id = 'inflow:' || c.id::text "
            f"AND t.layer = ${n} AND t.feature_idx = ${n + 1})"
        )
        args.extend([layer, idx])
        n += 1
    clause = " AND ".join(where)

    async with db_pool.acquire() as conn:
        total = int(
            await conn.fetchval(
                f"SELECT count(*) FROM content_items c "
                f"LEFT JOIN feed_sources s ON s.id = c.source_id WHERE {clause}",
                *args,
            )
            or 0
        )
        doc_rows = await conn.fetch(
            f"""
            SELECT c.id, c.title, COALESCE(c.summary, '') AS body,
                   c.fetched_at, COALESCE(c.url, '') AS url,
                   COALESCE(s.name, '') AS source
              FROM content_items c
              LEFT JOIN feed_sources s ON s.id = c.source_id
             WHERE {clause}
             ORDER BY c.fetched_at DESC
             LIMIT {int(limit)}
            """,
            *args,
        )
        if br == "layer":
            bucket_rows = []
        elif br == "stream":
            bucket_rows = await conn.fetch(
                f"""
                SELECT date_trunc('{interval}', c.fetched_at) AS t,
                       'inflow' AS k, count(*)::int AS n
                  FROM content_items c
                  LEFT JOIN feed_sources s ON s.id = c.source_id
                 WHERE {clause}
                 GROUP BY 1, 2
                 ORDER BY 1
                """,
                *args,
            )
        else:
            bucket_rows = await conn.fetch(
                f"""
                SELECT date_trunc('{interval}', c.fetched_at) AS t,
                       COALESCE(s.name, '') AS k, count(*)::int AS n
                  FROM content_items c
                  LEFT JOIN feed_sources s ON s.id = c.source_id
                 WHERE {clause}
                 GROUP BY 1, 2
                 ORDER BY 1
                """,
                *args,
            )
        facet_rows = await conn.fetch(
            f"""
            SELECT COALESCE(s.name, '') AS k, count(*)::int AS n
              FROM content_items c
              LEFT JOIN feed_sources s ON s.id = c.source_id
             WHERE {clause}
             GROUP BY 1
             ORDER BY n DESC
            """,
            *args,
        )

    docs = [
        DiscoverDoc(
            id=f"inflow:{r['id']}",
            stream="inflow",
            source=str(r["source"] or ""),
            ts=_iso(r["fetched_at"]),
            title=str(r["title"] or ""),
            body=str(r["body"] or "")[:400],
            source_id=str(r["id"]),
            url=str(r["url"] or ""),
        )
        for r in doc_rows
    ]
    if clock == "salience":
        async with db_pool.acquire() as conn:
            sal_rows = await conn.fetch(
                f"""
                SELECT date_trunc('{interval}', created_at) AS m,
                       count(DISTINCT event_id)::int AS n,
                       COALESCE(sum(activation), 0) AS sal
                  FROM feature_tape
                 WHERE created_at >= $1 AND created_at <= $2
                 GROUP BY 1
                 ORDER BY 1
                """,
                start,
                end,
            )
            try:
                gpu_rows = await conn.fetch(
                    f"""
                    SELECT date_trunc('{interval}', minute) AS m,
                           COALESCE(sum(power_avg_w), 0) AS watts,
                           COALESCE(avg(util_avg_pct), 0) AS util
                      FROM meta.gpu_minute_stats
                     WHERE minute >= $1 AND minute <= $2
                     GROUP BY 1
                     ORDER BY 1
                    """,
                    start,
                    end,
                )
            except Exception:
                gpu_rows = []
        buckets = _fill_minutes(start, end, sal_rows, gpu_rows, interval)
    else:
        buckets = [
            DiscoverBucket(
                t=_iso(r["t"]),
                n=int(r["n"]),
                breakdown_key=str(r["k"] or ""),
            )
            for r in bucket_rows
        ]
    facets = [
        DiscoverFacet(key="inflow", kind="stream", count=total, salience=1.0)
    ]
    for r in facet_rows:
        name = str(r["k"] or "")
        if not name:
            continue
        facets.append(
            DiscoverFacet(
                key=name,
                kind="source",
                count=int(r["n"]),
                salience=float(r["n"]) / float(total) if total else 0.0,
            )
        )
    try:
        from .feature_tape import ensure_tape

        await ensure_tape(db_pool)
        facets.extend(await _feature_facets(db_pool, start))
    except Exception:
        pass
    return DiscoverSurface(
        buckets=buckets,
        docs=docs,
        facets=facets,
        total=total,
        window=win_label,
        query=query or "",
        scraped_at=scraped,
        interval=interval,
        last_salience_at=_iso(last_sal),
        next_episode=episode,
        clock=clock,
    )


async def _feature_facets(pool: Any, start) -> list[DiscoverFacet]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT layer, feature_idx, count(*)::int AS n, avg(activation) AS a
              FROM feature_tape
             WHERE ts >= $1
             GROUP BY 1, 2
             ORDER BY count(*) * avg(activation) DESC
             LIMIT 20
            """,
            start,
        )
    from .clt_skos_propose import load_pref_labels

    labels = load_pref_labels()
    out: list[DiscoverFacet] = []
    for r in rows:
        notation = f"{int(r['layer'])}:{int(r['feature_idx'])}"
        pref = labels.get(notation)
        key = f"{notation} · {pref}" if pref else notation
        n = int(r["n"])
        a = float(r["a"] or 0.0)
        out.append(
            DiscoverFacet(
                key=key,
                kind="feature",
                count=n,
                salience=n * a,
            )
        )
    return out
