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
from dataclasses import dataclass
from datetime import datetime, timezone
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

ACQUIRE_S = 1.0


def peek_landing() -> DiscoverSurface | None:
    """Last default-landing snapshot. No I/O."""
    return _landing_snap


def remember_landing(snap: DiscoverSurface) -> None:
    global _landing_snap, _last_refreshed_at
    _landing_snap = snap
    if snap.scraped_at:
        _last_refreshed_at = snap.scraped_at


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
    """True when the request is the default 36h landing (the MV)."""
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
    snap = surface_from_landing_rows(
        rows, limit=limit, gpu_rows=[], episode=None
    )
    remember_landing(snap)
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
