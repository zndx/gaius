"""ServerQuery FMP — live Financial Modeling Prep, key stays on Gaius.

Hermes / AgentRTC hop here over the lattice. Empty hits plus `note` is
honest (no key, rate limit, no matches). CPU only; no thinking GPU.
"""
from __future__ import annotations

from typing import Any

from gaius.engine.services.fmp_tools import BY_NAME, call_tool

FMP_STREAMS = frozenset(BY_NAME)
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
    args: dict[str, Any] = {"query": q, "symbol": q, "limit": n}
    raw = await call_tool(kind, args)
    note = str(raw.get("error") or raw.get("note") or "")
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
