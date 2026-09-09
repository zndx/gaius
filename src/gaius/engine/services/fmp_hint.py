"""ServerQuery FMP — live Financial Modeling Prep, key stays on Gaius.

Hermes / AgentRTC hop here over the lattice. Empty hits plus `note` is
honest (no key, rate limit, no matches). CPU only; no thinking GPU.
"""
from __future__ import annotations

import logging
from typing import Any

from gaius.engine.services.fmp_client import FMPClientError, get_fmp_client

log = logging.getLogger("gaius.engine.services.fmp_hint")

FMP_STREAMS = frozenset({"search", "news", "quote"})
_MAX = 8


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
        return "FMP: " + "; ".join(bits)
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
    n = max(1, min(int(limit or 6), _MAX))
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
    try:
        client = await get_fmp_client()
    except Exception as e:
        empty["note"] = str(e)[:200]
        return empty
    hits: list[dict[str, str]] = []
    note = ""
    try:
        if kind == "search":
            rows = await client.search_ticker(q, limit=n)
            for row in rows:
                hits.append(
                    _hit(
                        symbol=str(row.get("symbol") or ""),
                        title=str(row.get("name") or ""),
                        exchange=str(row.get("exchange") or ""),
                        source="search",
                    )
                )
        elif kind == "news":
            rows = await client.get_latest_stock_news(limit=max(n, 15))
            want = q.upper()
            for row in rows:
                if not isinstance(row, dict):
                    continue
                sym = str(row.get("symbol") or "").upper()
                title = str(row.get("title") or row.get("text") or "")
                if want and want != sym and want not in title.upper():
                    continue
                hits.append(
                    _hit(
                        symbol=sym,
                        title=str(row.get("title") or row.get("text") or ""),
                        snippet=str(row.get("text") or row.get("snippet") or ""),
                        url=str(row.get("url") or ""),
                        as_of=str(row.get("publishedDate") or row.get("date") or ""),
                        source="news",
                    )
                )
                if len(hits) >= n:
                    break
        else:
            profile = await client.get_company_profile(q)
            if profile is None:
                note = "no profile"
            else:
                cap = getattr(profile, "market_cap", 0) or 0
                snippet = " · ".join(
                    p
                    for p in (
                        getattr(profile, "sector", "") or "",
                        getattr(profile, "industry", "") or "",
                        f"cap {cap:,}" if cap else "",
                    )
                    if p
                )
                desc = getattr(profile, "description", "") or ""
                hits.append(
                    _hit(
                        symbol=getattr(profile, "symbol", "") or q,
                        title=getattr(profile, "company_name", "") or q,
                        snippet=snippet or _clip(desc, 200),
                        url=getattr(profile, "website", "") or "",
                        exchange=getattr(profile, "exchange", "") or "",
                        source="quote",
                    )
                )
    except FMPClientError as e:
        note = str(e)[:200]
    except Exception as e:
        log.warning("fmp collect failed: %s", e)
        note = str(e)[:200]
    finally:
        try:
            await client.__aexit__(None, None, None)
        except Exception:
            pass
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
