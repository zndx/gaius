"""36h Discover landing materialized view — instant default reads.

The default landing (36h, no pins/text) is served from
``discover_landing_36h``. REFRESH MATERIALIZED VIEW CONCURRENTLY runs in
the background so the UI keeps reading the previous snapshot until the
new one is committed. Metaflow end requests the refresh via gRPC.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import statistics
import time
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from gaius.engine.services.discover_surface import (
    DiscoverDoc,
    DiscoverError,
    DiscoverFacet,
    DiscoverQuery,
    DiscoverSurface,
    minted_feature_facet,
    _fill_minutes,
    _window_token,
)

logger = logging.getLogger(__name__)

GURU_NOLANDING = (
    "Discover 36h landing snapshot is not materialized.\n"
    "  Guru: #DI.00000007.NOLANDING\n"
    "  Try: /health fix discover\n"
    "  Or:  dbmate up && /discover refresh"
)
GURU_REFRESH = (
    "Discover landing refresh failed.\n"
    "  Guru: #DI.00000008.REFRESH\n"
    "  Try: /health fix discover"
)

REFRESH_SQL = "REFRESH MATERIALIZED VIEW CONCURRENTLY public.discover_landing_36h"
SELECT_SQL = "SELECT kind, key, payload FROM public.discover_landing_36h"
EXISTS_SQL = (
    "SELECT 1 FROM pg_matviews "
    "WHERE schemaname = 'public' AND matviewname = 'discover_landing_36h'"
)

_refresh_lock = asyncio.Lock()
_refresh_task: asyncio.Task[None] | None = None
_refresh_again = False
_last_refreshed_at = ""
_landing_snap: DiscoverSurface | None = None
_strip_workflows = 0
_strip_watts = 0.0
_strip_articles = 0
_strip_projects = 0
_strip_thoughts = 0
_strip_watts_live = False
_strip_watts_at = 0.0
_strip_terms_skos = 0
_strip_terms_cites = 0
_strip_agenda_min = 0.0
_strip_agenda_max = 0.0
_strip_agenda_std = 0.0
_strip_salience_peak = 0.0
_strip_cognition_tokens = 0
_watts_task: asyncio.Task[None] | None = None

ACQUIRE_S = 1.0
WATTS_TTL_S = 15.0
_SKOS_IRI = re.compile(r"\b(?:skos|owl):[A-Za-z][\w-]*", re.I)
_SKOS_WIKI = re.compile(
    r"\[\[[^\]]*(?:ontology|heuristics|skos)[^\]]*\]\]", re.I
)


def peek_landing() -> DiscoverSurface | None:
    """Last default-landing snapshot. No I/O."""
    return _landing_snap


def remember_landing(snap: DiscoverSurface) -> None:
    global _landing_snap, _last_refreshed_at
    _landing_snap = snap
    if snap.scraped_at:
        _last_refreshed_at = snap.scraped_at


def landing_updating() -> bool:
    task = _refresh_task
    return task is not None and not task.done()


def next_waiting_at(now: datetime | None = None) -> datetime:
    """Soonest salience cron — no DB."""
    from gaius.engine.services.discover_surface import next_cron

    ts = now or datetime.now(timezone.utc)
    return min(
        next_cron(ts, "*/5", "*"),
        next_cron(ts, "17", "*/4"),
        next_cron(ts, "35", "0,4,8,12,16,20"),
        next_cron(ts, "45", "*/2"),
    )


CHARS_PER_TOKEN = 4


def _bytes_to_tokens(n: int) -> int:
    return max(0, (int(n) + CHARS_PER_TOKEN - 1) // CHARS_PER_TOKEN)


def terms_in_text(text: str) -> set[str]:
    """OWL/SKOS CURIE + ontology/heuristic wiki links in article prose."""
    found: set[str] = set()
    for m in _SKOS_IRI.findall(text or ""):
        found.add(m.lower())
    for m in _SKOS_WIKI.findall(text or ""):
        found.add(m.lower())
    return found


def article_term_stats() -> tuple[int, int]:
    from gaius.engine.services.agenda_notes import kb_root_from_env
    from gaius.engine.services.summary_lineup import _article_cards

    kb = kb_root_from_env()
    cards = _article_cards(kb)
    terms: set[str] = set()
    cites = 0
    for path in cards:
        text = path.read_text(encoding="utf-8", errors="replace")
        terms |= terms_in_text(text)
        src = path.parent / "sources"
        if src.is_dir():
            cites += sum(1 for p in src.glob("*.md") if p.is_file())
    return len(terms), cites


def agenda_day_stats() -> tuple[float, float, float]:
    from gaius.engine.services.agenda_notes import (
        item_calendar_day,
        kb_root_from_env,
        list_items,
    )

    kb = kb_root_from_env()
    now = datetime.now(timezone.utc)
    items = list_items(kb, window_days=14, now=now)
    today = now.date()
    days: Counter[str] = Counter()
    for i in range(14):
        days[(today - timedelta(days=i)).isoformat()] = 0
    for item in items:
        day = item_calendar_day(item)
        if day in days:
            days[day] += 1
    vals = list(days.values())
    if not vals:
        return 0.0, 0.0, 0.0
    std = statistics.pstdev(vals) if len(vals) > 1 else 0.0
    return float(min(vals)), float(max(vals)), float(std)


def _fifo_tokens(svc: Any) -> int:
    buf = getattr(svc, "_buffer", None) if svc is not None else None
    if buf is None:
        return 0
    return _bytes_to_tokens(int(getattr(buf, "current_bytes", 0) or 0))


def cognition_buffer_tokens(services: Any = None) -> int:
    """HN ambient + FMP prospects + theta/thought tokens.

    FMP is the prospects FIFO (user 'FPM'). HN is ambient. Theta-oriented
    is sitrep/agent state plus recent cognition_thoughts chars.
    """
    total = int(_strip_cognition_tokens)
    if services is None:
        return total
    ambient = getattr(services, "ambient_service", None)
    prospects = getattr(services, "prospects_service", None)
    hn = _fifo_tokens(ambient)
    fmp = _fifo_tokens(prospects)
    total += hn
    total += fmp
    theta = getattr(services, "theta_service", None)
    agent = getattr(theta, "_agent", None) if theta is not None else None
    if agent is not None:
        sitrep = getattr(agent, "_last_sitrep", None) or getattr(
            agent, "_last_validation", None
        )
        if sitrep is not None:
            total += _bytes_to_tokens(len(repr(sitrep).encode("utf-8")))
    amb_on = bool(
        getattr(ambient, "_daemon_running", False) or getattr(ambient, "_running", False)
    )
    prosp_on = bool(getattr(prospects, "_running", False))
    if (amb_on and hn == 0) or (prosp_on and fmp == 0):
        logger.error(
            "Cognition FIFOs empty while services are running "
            "(hn_tokens=%s fmp_tokens=%s).\n"
            "  Guru: #DI.00000010.EMPTYBUF\n"
            "  HN fetch must not wait on thinking Complete; "
            "FMP ingest must hit the live ProspectsService FIFO.",
            hn,
            fmp,
        )
    return total


def _peak_salience() -> float:
    snap = _landing_snap
    if snap is not None and snap.buckets:
        return max((float(b.salience or 0.0) for b in snap.buckets), default=0.0)
    return float(_strip_salience_peak)


@dataclass(frozen=True)
class LandingStrip:
    updating: bool
    workflows: int
    waiting_at: str
    watts: float
    watts_live: bool
    articles: int
    projects: int
    thoughts: int
    terms_skos: int
    terms_cites: int
    agenda_min: float
    agenda_max: float
    agenda_std: float
    salience_peak: float
    cognition_tokens: int


def landing_strip(
    *, extra_workflows: int = 0, services: Any = None
) -> LandingStrip:
    _maybe_kick_watts()
    wait = next_waiting_at()
    return LandingStrip(
        updating=landing_updating(),
        workflows=max(0, int(_strip_workflows) + max(0, extra_workflows)),
        waiting_at=wait.isoformat().replace("+00:00", "Z"),
        watts=float(_strip_watts or 0.0),
        watts_live=bool(_strip_watts_live),
        articles=int(_strip_articles),
        projects=int(_strip_projects),
        thoughts=int(_strip_thoughts),
        terms_skos=int(_strip_terms_skos),
        terms_cites=int(_strip_terms_cites),
        agenda_min=float(_strip_agenda_min),
        agenda_max=float(_strip_agenda_max),
        agenda_std=float(_strip_agenda_std),
        salience_peak=_peak_salience(),
        cognition_tokens=cognition_buffer_tokens(services),
    )


def _maybe_kick_watts() -> None:
    global _watts_task
    if _strip_watts_live and (time.monotonic() - _strip_watts_at) < WATTS_TTL_S:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    if _watts_task is not None and not _watts_task.done():
        return
    _watts_task = loop.create_task(_scrape_watts_safe(), name="discover-watts")


async def _scrape_watts_safe() -> None:
    global _strip_watts, _strip_watts_live, _strip_watts_at
    try:
        from gaius.engine.services.signals_telemetry import scrape_snapshot

        snap = await scrape_snapshot()
        _strip_watts = float(snap.get("total_w") or 0.0)
        _strip_watts_live = True
        _strip_watts_at = time.monotonic()
        logger.info("discover strip watts %.1f from Signals telemetry", _strip_watts)
    except Exception:
        logger.exception("Signals watts scrape failed")


def _refresh_lens_counts() -> None:
    global _strip_articles, _strip_projects
    global _strip_terms_skos, _strip_terms_cites
    global _strip_agenda_min, _strip_agenda_max, _strip_agenda_std
    from gaius.engine.services.agenda_notes import kb_root_from_env
    from gaius.engine.services.summary_lineup import _article_cards, _project_cards

    kb = kb_root_from_env()
    _strip_articles = len(_article_cards(kb))
    _strip_projects = len(_project_cards(kb))
    try:
        _strip_terms_skos, _strip_terms_cites = article_term_stats()
    except Exception:
        logger.exception("discover strip article terms failed")
    try:
        _strip_agenda_min, _strip_agenda_max, _strip_agenda_std = agenda_day_stats()
    except Exception:
        logger.exception("discover strip agenda stats failed")


async def refresh_landing_strip(db_pool: Any) -> None:
    """Fill strip cache. Must not nest an acquire on a held connection."""
    global _strip_workflows, _strip_thoughts, _strip_cognition_tokens
    global _strip_salience_peak
    try:
        _refresh_lens_counts()
    except Exception:
        logger.exception("discover strip lens counts failed")
    await _scrape_watts_safe()
    if db_pool is None:
        return
    try:
        conn = await db_pool.acquire(timeout=0.4)
    except Exception:
        logger.exception("discover strip db acquire failed")
        return
    try:
        try:
            thoughts = await conn.fetchval("SELECT count(*) FROM cognition_thoughts")
            if thoughts is not None:
                _strip_thoughts = int(thoughts)
        except Exception:
            logger.exception("discover strip thoughts count failed")
        try:
            running = await conn.fetchval(
                "SELECT count(*) FROM scheduled_tasks WHERE status = 'running'"
            )
            if running is not None:
                _strip_workflows = int(running)
        except Exception:
            logger.exception("discover strip workflow count failed")
        try:
            chars = await conn.fetchval(
                """
                SELECT COALESCE(sum(
                    length(coalesce(content, '')) + length(coalesce(summary, ''))
                ), 0)
                  FROM cognition_thoughts
                 WHERE created_at >= now() - interval '36 hours'
                """
            )
            if chars is not None:
                _strip_cognition_tokens = _bytes_to_tokens(int(chars))
        except Exception:
            logger.exception("discover strip cognition tokens failed")
        try:
            peak = await conn.fetchval(
                """
                SELECT COALESCE(max(s), 0) FROM (
                  SELECT sum(activation) AS s
                    FROM feature_tape
                   WHERE created_at >= now() - interval '36 hours'
                   GROUP BY date_trunc('hour', created_at)
                ) t
                """
            )
            if peak is not None:
                _strip_salience_peak = float(peak)
        except Exception:
            logger.exception("discover strip salience peak failed")
    finally:
        await db_pool.release(conn)


@dataclass(frozen=True)
class RefreshAccepted:
    started: bool
    coalesced: bool
    refreshed_at: str


def uses_landing_mv(
    window: str,
    parsed: DiscoverQuery,
    from_ts: str = "",
    to_ts: str = "",
) -> bool:
    """True when the request is the explicit 36h landing (the MV)."""
    if from_ts.strip() and to_ts.strip():
        return False
    if _window_token(window) != "36h":
        return False
    if parsed.text or parsed.source or parsed.features:
        return False
    if parsed.stream and parsed.stream != "inflow":
        return False
    return True


def _as_dt(raw: object) -> datetime:
    if isinstance(raw, datetime):
        ts = raw
    else:
        ts = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)


def _payload(row: Any) -> dict[str, Any]:
    p = row["payload"]
    if p is None:
        return {}
    if isinstance(p, dict):
        return p
    if isinstance(p, (bytes, bytearray)):
        p = p.decode("utf-8")
    if isinstance(p, str):
        try:
            parsed = json.loads(p)
        except json.JSONDecodeError as e:
            raise DiscoverError(GURU_NOLANDING) from e
        if isinstance(parsed, dict):
            return parsed
    raise DiscoverError(GURU_NOLANDING)


def surface_from_landing_rows(
    rows: list[Any],
    *,
    limit: int,
    gpu_rows: list[Any],
    episode: Any,
) -> DiscoverSurface:
    """Assemble DiscoverSurface from MV rows. Fail-fast without meta."""
    docs_raw: list[dict[str, Any]] = []
    src_rows: list[tuple[str, int]] = []
    feat_rows: list[dict[str, Any]] = []
    sal_rows: list[dict[str, Any]] = []
    meta: dict[str, Any] | None = None
    for row in rows:
        kind = str(row["kind"] or "")
        payload = _payload(row)
        if kind == "doc":
            docs_raw.append(payload)
        elif kind == "src":
            src_rows.append((str(row["key"] or ""), int(payload.get("n") or 0)))
        elif kind == "feat":
            feat_rows.append(payload)
        elif kind == "bucket":
            sal_rows.append(
                {"m": _as_dt(payload["t"]), "n": int(payload.get("n") or 0), "sal": float(payload.get("sal") or 0.0)}
            )
        elif kind == "meta":
            meta = payload
    if meta is None:
        raise DiscoverError(GURU_NOLANDING)

    start = _as_dt(meta["start_ts"])
    end = _as_dt(meta["end_ts"])
    total = int(meta.get("total") or 0)
    refreshed = str(meta.get("refreshed_at") or "")
    last_sal = str(meta.get("last_salience_at") or "")
    docs_raw.sort(key=lambda d: str(d.get("fetched_at") or ""), reverse=True)
    docs = [
        DiscoverDoc(
            id=f"inflow:{r.get('id')}",
            stream="inflow",
            source=str(r.get("source") or ""),
            ts=str(r.get("fetched_at") or ""),
            title=str(r.get("title") or ""),
            body=str(r.get("body") or "")[:400],
            source_id=str(r.get("id") or ""),
            url=str(r.get("url") or ""),
        )
        for r in docs_raw[: int(limit)]
    ]
    buckets = _fill_minutes(start, end, sal_rows, gpu_rows, "hour")
    facets = [DiscoverFacet(key="inflow", kind="stream", count=total, salience=1.0)]
    for name, n in sorted(src_rows, key=lambda x: x[1], reverse=True):
        if not name:
            continue
        facets.append(
            DiscoverFacet(
                key=name,
                kind="source",
                count=n,
                salience=float(n) / float(total) if total else 0.0,
            )
        )
    from gaius.engine.services.clt_skos_propose import load_pref_labels

    minted = load_pref_labels()
    feat_rows.sort(key=lambda r: int(r.get("n") or 0), reverse=True)
    n_feat = 0
    for r in feat_rows:
        n = int(r.get("n") or 0)
        a = float(r.get("a") or 0.0)
        facet = minted_feature_facet(
            int(r["layer"]), int(r["feature_idx"]), n, n * a, minted
        )
        if facet is None:
            continue
        facets.append(facet)
        n_feat += 1
        if n_feat >= 20:
            break
    return DiscoverSurface(
        buckets=buckets,
        docs=docs,
        facets=facets,
        total=total,
        window="36h",
        query="",
        scraped_at=refreshed,
        interval="hour",
        last_salience_at=last_sal,
        next_episode=episode,
        clock="salience",
    )


async def load_landing_mv(db_pool: Any, *, limit: int) -> DiscoverSurface:
    cached = peek_landing()
    if db_pool is None:
        if cached is not None:
            return cached
        from gaius.engine.services.discover_surface import GURU_NODB

        raise DiscoverError(GURU_NODB)
    try:
        conn = await db_pool.acquire(timeout=ACQUIRE_S)
    except (TimeoutError, asyncio.TimeoutError, OSError) as e:
        if cached is not None:
            return cached
        raise DiscoverError(
            "Discover landing timed out waiting for postgres.\n"
            "  Guru: #DI.00000009.SLOWPOOL\n"
            "  Try: /discover refresh"
        ) from e
    try:
        try:
            rows = await conn.fetch(SELECT_SQL)
        except Exception as e:
            name = type(e).__name__
            if "UndefinedTable" in name or "UndefinedTableError" in name:
                raise DiscoverError(GURU_NOLANDING) from e
            raise
    finally:
        await db_pool.release(conn)
    from datetime import timedelta

    from gaius.engine.services.warehouse_ingest import fetch_gpu_hist_buckets

    end = datetime.now(timezone.utc)
    start = end - timedelta(hours=36)
    try:
        gpu_rows = await fetch_gpu_hist_buckets(start, end, "hour")
    except Exception as e:
        from gaius.engine.services.discover_surface import DiscoverError

        raise DiscoverError(
            "Discover landing GPU hist failed reading warehouse gpu_metrics.\n"
            "  Guru: #COG.00000031.NOWHFDW\n"
            f"  {e}"
        ) from e
    snap = surface_from_landing_rows(
        rows, limit=limit, gpu_rows=gpu_rows, episode=None
    )
    remember_landing(snap)
    if _strip_articles == 0 and _strip_projects == 0 and _strip_thoughts == 0:
        asyncio.create_task(
            refresh_landing_strip(db_pool), name="discover-strip-seed"
        )
    return snap


async def last_landing_refreshed_at(db_pool: Any) -> str:
    async with db_pool.acquire() as conn:
        val = await conn.fetchval(
            """
            SELECT payload->>'refreshed_at'
              FROM public.discover_landing_36h
             WHERE kind = 'meta' AND key = 'snapshot'
            """
        )
    return str(val or "")


async def refresh_discover_landing_now(db_pool: Any) -> str:
    """Blocking CONCURRENTLY refresh. Must not run inside a transaction."""
    if db_pool is None:
        from gaius.engine.services.discover_surface import GURU_NODB

        raise DiscoverError(GURU_NODB)
    async with db_pool.acquire() as conn:
        exists = await conn.fetchval(EXISTS_SQL)
        if exists is None:
            raise DiscoverError(GURU_NOLANDING)
        try:
            await conn.execute(REFRESH_SQL)
        except Exception as e:
            raise DiscoverError(f"{GURU_REFRESH}\n  {e}") from e
    ts = await last_landing_refreshed_at(db_pool)
    global _last_refreshed_at
    _last_refreshed_at = ts
    logger.info("discover_landing_36h refreshed at %s", ts)
    return ts


async def _refresh_loop(db_pool: Any) -> None:
    global _refresh_again, _refresh_task
    while True:
        async with _refresh_lock:
            _refresh_again = False
        try:
            await refresh_discover_landing_now(db_pool)
            await load_landing_mv(db_pool, limit=50)
            await refresh_landing_strip(db_pool)
        except Exception:
            logger.exception("discover_landing_36h concurrent refresh failed")
            raise
        async with _refresh_lock:
            if not _refresh_again:
                _refresh_task = None
                return


async def request_discover_landing_refresh(
    db_pool: Any, *, reason: str = ""
) -> RefreshAccepted:
    """Accept a refresh. Runs CONCURRENTLY in the background. Coalesces."""
    global _refresh_task, _refresh_again
    if db_pool is None:
        from gaius.engine.services.discover_surface import GURU_NODB

        raise DiscoverError(GURU_NODB)
    async with _refresh_lock:
        task = _refresh_task
        if task is not None and not task.done():
            _refresh_again = True
            logger.info("discover_landing_36h refresh coalesced (%s)", reason or "-")
            return RefreshAccepted(
                started=False, coalesced=True, refreshed_at=_last_refreshed_at
            )
        _refresh_again = False
        _refresh_task = asyncio.create_task(
            _refresh_loop(db_pool), name="discover-landing-refresh"
        )
    logger.info("discover_landing_36h refresh started (%s)", reason or "-")
    return RefreshAccepted(
        started=True, coalesced=False, refreshed_at=_last_refreshed_at
    )
