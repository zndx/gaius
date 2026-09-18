"""FMP proxy tools — one catalog, three faces (gRPC / MCP / CLI).

AgentRTC hops here via ServerQuery FMP. MCP and `gaius-cli /fmp` call
``FmpListTools`` / ``FmpCall``. Handlers live in this module; they are
the only FMP business logic. Starter Annual: US, annual statements,
no 13F / transcripts / bulk.

CPU only. The key stays on Gaius.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from gaius.engine.services.fmp_client import FMPClientError, get_fmp_client

log = logging.getLogger("gaius.engine.services.fmp_tools")

Handler = Callable[[Any, dict[str, Any]], Awaitable[dict[str, Any]]]


@dataclass(frozen=True)
class FmpTool:
    name: str
    description: str
    input_schema: dict[str, Any]
    handler: Handler


def _clip(text: str, n: int = 400) -> str:
    t = " ".join((text or "").split())
    if len(t) <= n:
        return t
    return t[: n - 1].rstrip() + "…"


def _sym(args: dict[str, Any]) -> str:
    return str(args.get("symbol") or args.get("query") or "").strip().upper()


def _lim(args: dict[str, Any], default: int, hi: int) -> int:
    try:
        n = int(args.get("limit") or default)
    except (TypeError, ValueError):
        n = default
    return max(1, min(n, hi))


async def _search(client: Any, args: dict[str, Any]) -> dict[str, Any]:
    q = str(args.get("query") or args.get("symbol") or "").strip()
    if not q:
        return {"items": [], "note": "empty query"}
    rows = await client.search_ticker(q, limit=_lim(args, 8, 20))
    return {"items": rows, "note": "" if rows else "no matches"}


def _quote_item(row: dict[str, Any], sym: str) -> dict[str, Any]:
    price = row.get("price")
    chg = row.get("change")
    pct = row.get("changesPercentage", row.get("changePercentage"))
    vol = row.get("volume")
    name = str(row.get("name") or row.get("companyName") or sym)
    snippet = " · ".join(
        p
        for p in (
            f"px={price}" if price is not None else "",
            f"chg={chg}" if chg is not None else "",
            f"{pct}%" if pct is not None else "",
            f"vol={vol}" if vol is not None else "",
        )
        if p
    )
    return {
        "symbol": str(row.get("symbol") or sym).upper(),
        "name": name,
        "title": f"{name} {price}".strip() if price is not None else name,
        "price": price,
        "change": chg,
        "changesPercentage": pct,
        "volume": vol,
        "dayLow": row.get("dayLow"),
        "dayHigh": row.get("dayHigh"),
        "yearLow": row.get("yearLow"),
        "yearHigh": row.get("yearHigh"),
        "exchange": str(row.get("exchange") or ""),
        "snippet": snippet,
        "as_of": str(row.get("timestamp") or row.get("date") or ""),
        "source": "quote",
    }


async def _quote(client: Any, args: dict[str, Any]) -> dict[str, Any]:
    """Live price quote. Profile is a different stream."""
    sym = _sym(args)
    if not sym:
        return {"items": [], "note": "symbol required"}
    row = await client.get_quote(sym)
    if not row:
        return {"items": [], "note": "no quote"}
    item = _quote_item(row, sym)
    if item.get("price") is None:
        return {"items": [item], "note": "quote has no price"}
    return {"items": [item], "note": ""}


async def _profile(client: Any, args: dict[str, Any]) -> dict[str, Any]:
    sym = _sym(args)
    if not sym:
        return {"items": [], "note": "symbol required"}
    profile = await client.get_company_profile(sym)
    if profile is None:
        return {"items": [], "note": "no profile"}
    cap = getattr(profile, "market_cap", 0) or 0
    item = {
        "symbol": getattr(profile, "symbol", "") or sym,
        "name": getattr(profile, "company_name", "") or sym,
        "title": getattr(profile, "company_name", "") or sym,
        "exchange": getattr(profile, "exchange", "") or "",
        "sector": getattr(profile, "sector", "") or "",
        "industry": getattr(profile, "industry", "") or "",
        "market_cap": cap,
        "website": getattr(profile, "website", "") or "",
        "description": _clip(getattr(profile, "description", "") or "", 500),
        "snippet": " · ".join(
            p
            for p in (
                getattr(profile, "sector", "") or "",
                getattr(profile, "industry", "") or "",
                f"cap={cap}" if cap else "",
            )
            if p
        ),
        "source": "profile",
    }
    return {"items": [item], "note": ""}


def _news_item(row: dict[str, Any], default_sym: str = "") -> dict[str, Any]:
    return {
        "symbol": str(row.get("symbol") or default_sym).upper(),
        "title": str(row.get("title") or row.get("text") or ""),
        "snippet": _clip(str(row.get("text") or row.get("snippet") or ""), 280),
        "url": str(row.get("url") or ""),
        "as_of": str(row.get("publishedDate") or row.get("date") or ""),
        "source": "news",
    }


async def _news(client: Any, args: dict[str, Any]) -> dict[str, Any]:
    kind = str(args.get("kind") or "stock").strip().lower()
    n = _lim(args, 12, 40)
    want = _sym(args)
    if want and kind != "general":
        rows = await client.get_stock_news(want, limit=n)
        items = [_news_item(r, want) for r in rows if isinstance(r, dict)][:n]
        return {"items": items, "note": "" if items else "no matches"}
    if kind == "general":
        rows = await client.get_latest_general_news(limit=n)
    else:
        rows = await client.get_latest_stock_news(limit=max(n, 15))
    items = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        items.append(_news_item(row, want))
        if len(items) >= n:
            break
    return {"items": items, "note": "" if items else "no matches"}


async def _filings(client: Any, args: dict[str, Any]) -> dict[str, Any]:
    sym = _sym(args)
    if not sym:
        return {"items": [], "note": "symbol required"}
    ftype = str(args.get("form") or args.get("filing_type") or "").strip() or None
    rows = await client.get_sec_filings(sym, filing_type=ftype, limit=_lim(args, 8, 40))
    items = []
    for f in rows:
        form = getattr(f, "filing_type", "") or ""
        filed = getattr(f, "filing_date", "") or getattr(f, "accepted_date", "") or ""
        items.append(
            {
                "symbol": getattr(f, "symbol", "") or sym,
                "form": form,
                "filed": filed,
                "title": " ".join(p for p in (form, filed) if p).strip() or form,
                "url": getattr(f, "final_link", "") or "",
                "as_of": filed,
                "source": "filings",
            }
        )
    return {"items": items, "note": "" if items else "no filings"}


_SKIP_SNIP = {
    "symbol",
    "title",
    "name",
    "url",
    "source",
    "reportedCurrency",
    "cik",
    "fillingDate",
    "acceptedDate",
    "calendarYear",
    "period",
    "link",
    "finalLink",
}


def _numeric_snippet(row: dict[str, Any]) -> str:
    bits: list[str] = []
    for k, v in row.items():
        if k in _SKIP_SNIP or v in (None, "", [], {}):
            continue
        if isinstance(v, bool):
            continue
        if isinstance(v, (int, float)) or (
            isinstance(v, str) and v[:1].isdigit()
        ):
            bits.append(f"{k}={v}")
        if len(bits) >= 8:
            break
    return " · ".join(bits)


def _decorate_financials(rows: list[dict[str, Any]], *, source: str, sym: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        item = dict(row)
        as_of = str(item.get("date") or item.get("calendarYear") or item.get("period") or "")
        item.setdefault("symbol", sym)
        item.setdefault("as_of", as_of)
        item.setdefault("source", source)
        item.setdefault("title", as_of or source)
        item.setdefault("snippet", _numeric_snippet(item))
        out.append(item)
    return out


async def _statement(client: Any, args: dict[str, Any]) -> dict[str, Any]:
    sym = _sym(args)
    if not sym:
        return {"items": [], "note": "symbol required"}
    kind = str(args.get("kind") or "income").strip().lower()
    rows = await client.get_annual_statement(sym, kind=kind, limit=_lim(args, 4, 8))
    items = _decorate_financials(rows, source="statement", sym=sym)
    return {"items": items, "note": "" if items else "no statement rows"}


async def _metrics(client: Any, args: dict[str, Any]) -> dict[str, Any]:
    sym = _sym(args)
    if not sym:
        return {"items": [], "note": "symbol required"}
    which = str(args.get("kind") or "metrics").strip().lower()
    if which in ("ratios", "ratio"):
        rows = await client.get_ratios(sym, limit=_lim(args, 4, 8))
    else:
        rows = await client.get_key_metrics(sym, limit=_lim(args, 4, 8))
    items = _decorate_financials(rows, source="metrics", sym=sym)
    return {"items": items, "note": "" if items else "no metrics"}


async def _calendar(client: Any, args: dict[str, Any]) -> dict[str, Any]:
    days = _lim(args, 14, 60)
    rows = await client.get_earnings_calendar(days=days)
    want = _sym(args)
    items = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        sym = str(row.get("symbol") or "").upper()
        if want and want != sym:
            continue
        items.append(row)
        if len(items) >= _lim(args, 12, 40):
            break
    return {"items": items, "note": "" if items else "no earnings in window"}


async def _employees(client: Any, args: dict[str, Any]) -> dict[str, Any]:
    sym = _sym(args)
    if not sym:
        return {"items": [], "note": "symbol required"}
    rows = await client.get_employee_counts(sym, limit=_lim(args, 16, 40))
    return {"items": rows, "note": "" if rows else "no employee counts"}


async def _eight_k(client: Any, args: dict[str, Any]) -> dict[str, Any]:
    """Per-symbol 8-K via SEC search (90d+). Market-wide latest only if no ticker."""
    from datetime import datetime, timedelta, timezone

    want = _sym(args)
    n = _lim(args, 15, 40)
    if want:
        to_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        from_date = (datetime.now(timezone.utc) - timedelta(days=365)).strftime("%Y-%m-%d")
        rows = await client.get_sec_filings(
            want,
            filing_type="8-K",
            limit=n,
            from_date=from_date,
            to_date=to_date,
        )
        items = []
        for f in rows:
            form = getattr(f, "filing_type", "") or "8-K"
            filed = getattr(f, "filing_date", "") or ""
            items.append(
                {
                    "symbol": getattr(f, "symbol", "") or want,
                    "form": form,
                    "filed": filed,
                    "title": " ".join(p for p in (form, filed) if p),
                    "url": getattr(f, "final_link", "") or "",
                    "as_of": filed,
                    "source": "eight_k",
                }
            )
        return {"items": items[:n], "note": "" if items else "no 8-K"}
    rows = await client.get_latest_8k(days=_lim(args, 7, 30), limit=n)
    items = [r for r in rows if isinstance(r, dict)]
    return {"items": items[:n], "note": "" if items else "no 8-K"}


async def _insider(client: Any, args: dict[str, Any]) -> dict[str, Any]:
    want = _sym(args)
    n = _lim(args, 15, 40)
    if want:
        rows = await client.get_insider_trades(want, limit=n)
    else:
        rows = await client.get_latest_insider(limit=n)
    items = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        trans = str(row.get("transactionType") or row.get("type") or "")
        shares = row.get("securitiesTransacted") or row.get("securities") or ""
        price = row.get("price") or row.get("transactionPrice") or ""
        when = str(row.get("transactionDate") or row.get("filingDate") or row.get("date") or "")
        who = str(row.get("reportingName") or row.get("name") or "")
        items.append(
            {
                "symbol": str(row.get("symbol") or want).upper(),
                "title": " ".join(p for p in (who, trans, when) if p).strip() or "insider",
                "snippet": " · ".join(
                    p for p in (f"shares={shares}" if shares != "" else "", f"px={price}" if price != "" else "") if p
                ),
                "url": str(row.get("link") or row.get("url") or ""),
                "as_of": when,
                "source": "insider",
            }
        )
        if len(items) >= n:
            break
    return {"items": items[:n], "note": "" if items else "no insider prints"}


async def _eod(client: Any, args: dict[str, Any]) -> dict[str, Any]:
    """Daily OHLC for a ticker — AgentRTC curves."""
    from datetime import datetime, timedelta, timezone

    sym = _sym(args)
    if not sym:
        return {"items": [], "note": "symbol required"}
    to_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    from_date = (datetime.now(timezone.utc) - timedelta(days=90)).strftime("%Y-%m-%d")
    bars = await client.get_historical_eod(sym, from_date=from_date, to_date=to_date)
    items = []
    for b in bars[-_lim(args, 30, 90) :]:
        if not isinstance(b, dict):
            continue
        items.append(
            {
                "symbol": sym,
                "title": str(b.get("t") or ""),
                "as_of": str(b.get("t") or ""),
                "open": b.get("o"),
                "high": b.get("h"),
                "low": b.get("l"),
                "close": b.get("c"),
                "snippet": f"o={b.get('o')} h={b.get('h')} l={b.get('l')} c={b.get('c')}",
                "source": "eod",
            }
        )
    return {"items": items, "note": "" if items else "no eod bars"}


_SYM = {
    "type": "object",
    "properties": {
        "symbol": {"type": "string", "description": "Ticker, e.g. AAPL"},
        "query": {"type": "string", "description": "Ticker or company name"},
        "limit": {"type": "integer"},
    },
}


TOOLS: tuple[FmpTool, ...] = (
    FmpTool(
        "search",
        "Find US tickers by company name or fragment. Starter FMP.",
        {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Name or ticker fragment"},
                "limit": {"type": "integer"},
            },
            "required": ["query"],
        },
        _search,
    ),
    FmpTool(
        "quote",
        "Live quote: price, change, volume. Per-symbol. US Starter.",
        {**_SYM, "required": ["symbol"]},
        _quote,
    ),
    FmpTool(
        "profile",
        "Company profile: sector, industry, market cap, description. US Starter.",
        {**_SYM, "required": ["symbol"]},
        _profile,
    ),
    FmpTool(
        "news",
        "Per-symbol stock news when a ticker is given; latest market news if not.",
        {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "symbol": {"type": "string"},
                "kind": {"type": "string", "description": "stock | general"},
                "limit": {"type": "integer"},
            },
        },
        _news,
    ),
    FmpTool(
        "filings",
        "SEC filings for a US ticker (10-K/10-Q/8-K). Starter.",
        {
            "type": "object",
            "properties": {
                "symbol": {"type": "string"},
                "form": {"type": "string", "description": "10-K | 10-Q | 8-K"},
                "limit": {"type": "integer"},
            },
            "required": ["symbol"],
        },
        _filings,
    ),
    FmpTool(
        "statement",
        "Annual income, balance, or cash-flow statement. Starter is annual US.",
        {
            "type": "object",
            "properties": {
                "symbol": {"type": "string"},
                "kind": {"type": "string", "description": "income | balance | cash"},
                "limit": {"type": "integer"},
            },
            "required": ["symbol"],
        },
        _statement,
    ),
    FmpTool(
        "metrics",
        "Annual key metrics or financial ratios. Starter US.",
        {
            "type": "object",
            "properties": {
                "symbol": {"type": "string"},
                "kind": {"type": "string", "description": "metrics | ratios"},
                "limit": {"type": "integer"},
            },
            "required": ["symbol"],
        },
        _metrics,
    ),
    FmpTool(
        "calendar",
        "Upcoming earnings calendar (Starter). Optional symbol filter.",
        {
            "type": "object",
            "properties": {
                "symbol": {"type": "string"},
                "limit": {"type": "integer"},
            },
        },
        _calendar,
    ),
    FmpTool(
        "employees",
        "Historical employee counts from SEC filings.",
        {**_SYM, "required": ["symbol"]},
        _employees,
    ),
    FmpTool(
        "eight_k",
        "8-K filings for a ticker (SEC search, last year). Market-wide latest if no symbol.",
        {
            "type": "object",
            "properties": {
                "symbol": {"type": "string"},
                "limit": {"type": "integer"},
            },
        },
        _eight_k,
    ),
    FmpTool(
        "insider",
        "Insider trades for a ticker. Market-wide latest if no symbol.",
        {
            "type": "object",
            "properties": {
                "symbol": {"type": "string"},
                "limit": {"type": "integer"},
            },
        },
        _insider,
    ),
    FmpTool(
        "eod",
        "Daily OHLC for a ticker (last 90 days). For AgentRTC price series.",
        {**_SYM, "required": ["symbol"]},
        _eod,
    ),
)

BY_NAME: dict[str, FmpTool] = {t.name: t for t in TOOLS}
# AgentRTC / ServerQuery aliases
BY_NAME["8k"] = BY_NAME["eight_k"]
BY_NAME["eightk"] = BY_NAME["eight_k"]
BY_NAME["price"] = BY_NAME["eod"]


def list_tools() -> list[dict[str, Any]]:
    """MCP ListTools-shaped descriptors (engine is the SoR)."""
    return [
        {
            "name": f"fmp_{t.name}",
            "description": t.description,
            "inputSchema": t.input_schema,
        }
        for t in TOOLS
    ]


async def call_tool(name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    raw = (name or "").strip().lower()
    if raw.startswith("fmp_"):
        raw = raw[4:]
    tool = BY_NAME.get(raw)
    if tool is None:
        return {
            "ok": False,
            "error": f"unknown FMP tool {name!r}. Starter tools: {', '.join(t.name for t in TOOLS)}",
            "items": [],
        }
    args = dict(arguments or {})
    client = await get_fmp_client()
    try:
        out = await tool.handler(client, args)
    except FMPClientError as e:
        return {"ok": False, "error": str(e), "items": []}
    except Exception as e:
        log.warning("fmp tool %s failed: %s", tool.name, e)
        return {"ok": False, "error": str(e)[:300], "items": []}
    finally:
        try:
            await client.__aexit__(None, None, None)
        except Exception:
            pass
    out.setdefault("ok", True)
    out["tool"] = tool.name
    return out


def mcp_name(stream: str) -> str:
    s = (stream or "").strip().lower()
    if s.startswith("fmp_"):
        return s
    return f"fmp_{s}" if s in BY_NAME else s
