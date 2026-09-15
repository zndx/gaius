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


async def _quote(client: Any, args: dict[str, Any]) -> dict[str, Any]:
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
        "exchange": getattr(profile, "exchange", "") or "",
        "sector": getattr(profile, "sector", "") or "",
        "industry": getattr(profile, "industry", "") or "",
        "market_cap": cap,
        "website": getattr(profile, "website", "") or "",
        "description": _clip(getattr(profile, "description", "") or "", 500),
    }
    return {"items": [item], "note": ""}


async def _news(client: Any, args: dict[str, Any]) -> dict[str, Any]:
    kind = str(args.get("kind") or "stock").strip().lower()
    n = _lim(args, 12, 40)
    want = _sym(args)
    if kind == "general":
        rows = await client.get_latest_general_news(limit=n)
    else:
        rows = await client.get_latest_stock_news(limit=max(n, 15))
    items = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        sym = str(row.get("symbol") or "").upper()
        title = str(row.get("title") or row.get("text") or "")
        if want and want != sym and want not in title.upper():
            continue
        items.append(
            {
                "symbol": sym,
                "title": title,
                "snippet": _clip(str(row.get("text") or row.get("snippet") or ""), 280),
                "url": str(row.get("url") or ""),
                "as_of": str(row.get("publishedDate") or row.get("date") or ""),
            }
        )
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
        items.append(
            {
                "symbol": getattr(f, "symbol", "") or sym,
                "form": getattr(f, "filing_type", "") or "",
                "filed": getattr(f, "filing_date", "") or getattr(f, "accepted_date", "") or "",
                "title": getattr(f, "filing_type", "") or "",
                "url": getattr(f, "final_link", "") or "",
            }
        )
    return {"items": items, "note": "" if items else "no filings"}


async def _statement(client: Any, args: dict[str, Any]) -> dict[str, Any]:
    sym = _sym(args)
    if not sym:
        return {"items": [], "note": "symbol required"}
    kind = str(args.get("kind") or "income").strip().lower()
    rows = await client.get_annual_statement(sym, kind=kind, limit=_lim(args, 4, 8))
    return {"items": rows, "note": "" if rows else "no statement rows"}


async def _metrics(client: Any, args: dict[str, Any]) -> dict[str, Any]:
    sym = _sym(args)
    if not sym:
        return {"items": [], "note": "symbol required"}
    which = str(args.get("kind") or "metrics").strip().lower()
    if which in ("ratios", "ratio"):
        rows = await client.get_ratios(sym, limit=_lim(args, 4, 8))
    else:
        rows = await client.get_key_metrics(sym, limit=_lim(args, 4, 8))
    return {"items": rows, "note": "" if rows else "no metrics"}


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
    rows = await client.get_latest_8k(days=_lim(args, 7, 30), limit=_lim(args, 15, 40))
    want = _sym(args)
    items = [r for r in rows if isinstance(r, dict)]
    if want:
        items = [
            r
            for r in items
            if str(r.get("symbol") or "").upper() == want
            or want in str(r.get("title") or "").upper()
        ]
    return {"items": items[: _lim(args, 15, 40)], "note": "" if items else "no 8-K"}


async def _insider(client: Any, args: dict[str, Any]) -> dict[str, Any]:
    rows = await client.get_latest_insider(limit=_lim(args, 15, 40))
    want = _sym(args)
    items = [r for r in rows if isinstance(r, dict)]
    if want:
        items = [r for r in items if str(r.get("symbol") or "").upper() == want]
    return {"items": items[: _lim(args, 15, 40)], "note": "" if items else "no insider prints"}


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
        "Company profile: sector, industry, market cap, description. US Starter.",
        {**_SYM, "required": ["symbol"]},
        _quote,
    ),
    FmpTool(
        "news",
        "Latest stock or general news. Optional symbol filter.",
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
        "Latest 8-K filings (market-wide, optional symbol filter).",
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
        "Latest insider trades (market-wide, optional symbol filter).",
        {
            "type": "object",
            "properties": {
                "symbol": {"type": "string"},
                "limit": {"type": "integer"},
            },
        },
        _insider,
    ),
)

BY_NAME: dict[str, FmpTool] = {t.name: t for t in TOOLS}
# AgentRTC / ServerQuery aliases
BY_NAME["quote"] = BY_NAME["quote"]
BY_NAME["profile"] = BY_NAME["quote"]
BY_NAME["8k"] = BY_NAME["eight_k"]
BY_NAME["eightk"] = BY_NAME["eight_k"]


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
