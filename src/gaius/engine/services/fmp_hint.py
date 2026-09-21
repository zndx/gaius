"""ServerQuery FMP — Gaius is the federated FMP SDK.

Live FMP is fetched here (key stays on Gaius). Warehouse-ready rows land
in Kudu ``fmp_*_tier0`` (Iceberg copy best-effort). The lattice wire is a
projection (FmpHint), not the SoR. Historical questions read the warehouse
first so Hermes does not re-hit FMP for last week's SLB numbers.
"""
from __future__ import annotations

import logging
from typing import Any

from gaius.engine.services.fmp_tools import BY_NAME, call_tool

log = logging.getLogger("gaius.engine.services.fmp_hint")

FMP_STREAMS = frozenset(BY_NAME)
_MAX = 8
_MAX_SERIES = 90


def _clip(text: str, n: int = 280) -> str:
    t = " ".join((text or "").split())
    if len(t) <= n:
        return t
    return t[: n - 1].rstrip() + "…"


def _hit(
    *,
    symbol: str,
    title: str,
    snippet: str = "",
    url: str = "",
    exchange: str = "",
    as_of: str = "",
    source: str,
) -> dict[str, str]:
    return {
        "symbol": (symbol or "").strip().upper(),
        "title": title or "",
        "snippet": _clip(snippet),
        "url": url or "",
        "exchange": exchange or "",
        "as_of": as_of or "",
        "source": source,
    }


def _spoken(hits: list[dict[str, str]], stream: str) -> str:
    bits: list[str] = []
    for h in hits[:4]:
        title = h.get("title") or h.get("symbol") or ""
        extra = h.get("exchange") or h.get("snippet") or ""
        if extra and extra != title:
            bits.append(f"{h.get('symbol') or ''} {title} ({_clip(extra, 80)})".strip())
        else:
            bits.append(f"{h.get('symbol') or ''} {title}".strip())
    if not bits:
        return ""
    if stream == "news":
        return "FMP news: " + "; ".join(bits)
    if stream == "quote":
        return "FMP quote: " + "; ".join(bits)
    if stream in ("eight_k", "8k"):
        return "FMP 8-K: " + "; ".join(bits)
    if stream == "insider":
        return "FMP insider: " + "; ".join(bits)
    return "FMP tickers: " + "; ".join(bits)


async def collect_fmp(
    query: str,
    *,
    stream: str = "search",
    limit: int = 6,
) -> dict[str, Any]:
    q = " ".join((query or "").split())
    kind = (stream or "search").strip().lower() or "search"
    if kind not in FMP_STREAMS:
        kind = "search"
    cap = _MAX_SERIES if kind in ("eod", "price") else _MAX
    n = max(1, min(int(limit or 6), cap))
    empty = {
        "project": "gaius",
        "query": q,
        "stream": kind,
        "hits": [],
        "note": "",
        "spoken": "",
    }
    if kind == "search" and not q:
        empty["note"] = "empty query"
        return empty
    if kind == "quote" and not q:
        empty["note"] = "symbol required"
        return empty
    if kind in ("eod", "price") and q:
        local = await recall_eod(q, limit=n)
        if len(local) >= 2:
            spoken = _spoken(local, "eod")
            return {
                "project": "gaius",
                "query": q,
                "stream": kind,
                "hits": local[:n],
                "note": "warehouse",
                "spoken": spoken,
            }
    args: dict[str, Any] = {"query": q, "symbol": q, "limit": n}
    raw = await call_tool(kind, args)
    note = str(raw.get("error") or raw.get("note") or "")
    try:
        await persist_stream(kind, list(raw.get("items") or []))
    except Exception:
        log.warning("fmp warehouse persist skipped", exc_info=True)
    hits: list[dict[str, str]] = []
    for row in raw.get("items") or []:
        if not isinstance(row, dict):
            continue
        snippet = str(
            row.get("snippet")
            or " · ".join(
                p
                for p in (
                    str(row.get("sector") or ""),
                    str(row.get("industry") or ""),
                )
                if p
            )
            or row.get("description")
            or row.get("filed")
            or ""
        )
        if not snippet:
            bits = []
            for k, v in row.items():
                if k in ("symbol", "title", "name", "url", "source", "exchange") or v in (
                    None,
                    "",
                    [],
                    {},
                ):
                    continue
                if isinstance(v, (int, float)) or (isinstance(v, str) and v[:1].isdigit()):
                    bits.append(f"{k}={v}")
                if len(bits) >= 8:
                    break
            snippet = " · ".join(bits)
        hits.append(
            _hit(
                symbol=str(row.get("symbol") or q),
                title=str(row.get("title") or row.get("name") or row.get("form") or ""),
                snippet=snippet,
                url=str(row.get("url") or row.get("website") or ""),
                exchange=str(row.get("exchange") or ""),
                as_of=str(row.get("as_of") or row.get("filed") or row.get("date") or ""),
                source=str(row.get("source") or kind),
            )
        )
        if len(hits) >= n:
            break
    spoken = _spoken(hits, kind)
    if not hits and not note:
        note = "no matches"
    return {
        "project": "gaius",
        "query": q,
        "stream": kind,
        "hits": hits[:n],
        "note": note,
        "spoken": spoken,
    }


async def persist_stream(kind: str, items: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Land warehouse-ready rows. Fail-soft: ServerQuery still answers."""
    from gaius.hx.fmp_warehouse import FLATTEN, STREAM_TABLE, land_kudu_async

    table = STREAM_TABLE.get(kind)
    fn = FLATTEN.get(table or "")
    if not table or fn is None or not items:
        return None
    rows = fn(items)
    if not rows:
        return None
    return await land_kudu_async(table, rows)


async def recall_eod(symbol: str, *, limit: int = 90) -> list[dict[str, str]]:
    """Local Kudu eod bars for a ticker. Empty if the warehouse is not ready."""
    from gaius.engine.services.warehouse_ingest import warehouse_dsn

    sym = (symbol or "").strip().upper()
    if not sym:
        return []
    try:
        import asyncpg
    except Exception:
        return []
    try:
        conn = await asyncpg.connect(warehouse_dsn(), timeout=8)
    except Exception:
        log.debug("fmp warehouse recall unavailable", exc_info=True)
        return []
    try:
        rows = await conn.fetch(
            """
            SELECT symbol, bar_date, open, high, low, close, volume
            FROM fmp_eod_tier0
            WHERE symbol = $1
            ORDER BY bar_date
            LIMIT $2
            """,
            sym,
            int(limit),
        )
    except Exception:
        log.debug("fmp eod recall query failed", exc_info=True)
        return []
    finally:
        await conn.close()
    hits: list[dict[str, str]] = []
    for row in rows:
        bar = str(row["bar_date"] or "")
        snippet = " · ".join(
            p
            for p in (
                f"o={row['open']}" if row["open"] is not None else "",
                f"h={row['high']}" if row["high"] is not None else "",
                f"l={row['low']}" if row["low"] is not None else "",
                f"c={row['close']}" if row["close"] is not None else "",
                f"vol={row['volume']}" if row["volume"] is not None else "",
            )
            if p
        )
        hits.append(
            _hit(
                symbol=str(row["symbol"] or sym),
                title=bar,
                snippet=snippet,
                as_of=bar,
                source="eod",
            )
        )
    return hits


def to_proto(d: dict[str, Any]):
    from gaius.engine.generated.zndx.engine.v1 import engine_pb2 as zpb

    hint = zpb.FmpHint(
        project=str(d.get("project") or "gaius"),
        query=str(d.get("query") or ""),
        stream=str(d.get("stream") or ""),
        note=str(d.get("note") or ""),
        spoken=str(d.get("spoken") or ""),
    )
    for h in d.get("hits") or []:
        hint.hits.add(
            symbol=str(h.get("symbol") or ""),
            title=str(h.get("title") or ""),
            snippet=str(h.get("snippet") or ""),
            url=str(h.get("url") or ""),
            exchange=str(h.get("exchange") or ""),
            as_of=str(h.get("as_of") or ""),
            source=str(h.get("source") or ""),
        )
    return hint
