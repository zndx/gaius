"""Terminal ACP MCP: slash + FMP tools only.

Grok session/new should attach this server, not the 180-tool gaius.mcp_server.
Qwen (via Complete) sees these as the option space. Slash /chart still hits
ask_present directly.
"""

from __future__ import annotations

import json
import os

from mcp.server.fastmcp import FastMCP

from gaius.mcp_server import _get_engine_client

server = FastMCP("gaius")


def _err(msg: str) -> str:
    return json.dumps({"error": msg}, indent=2)


@server.tool()
async def ask_present(
    symbol: str = "",
    title: str = "",
    bars: str = "",
    from_date: str = "",
    to_date: str = "",
    kind: str = "ohlc",
) -> str:
    """Present OHLC/table/links in the Ask panel. Engine FMP for EOD bars."""
    import httpx

    try:
        client = await _get_engine_client()
        if not client:
            return _err("Engine not available")
        built = await client.call(
            "Gaius",
            "AskPresent",
            {
                "kind": kind,
                "symbol": symbol,
                "title": title,
                "from_date": from_date,
                "to_date": to_date,
                "payload_json": bars,
            },
            timeout=30.0,
        )
        if built.get("error"):
            return json.dumps(built, indent=2)
        artifact = built.get("artifact") or {}
    except Exception as e:
        return _err(str(e))

    origin = os.environ.get("GAIUS_UI_ORIGIN", "http://127.0.0.1:9890").rstrip("/")
    posted = False
    post_error = ""
    try:
        async with httpx.AsyncClient(timeout=8.0) as hx:
            r = await hx.post(f"{origin}/api/gaius/v1/ask/artifacts", json=artifact)
            posted = r.status_code < 300
            if not posted:
                post_error = r.text[:300]
    except Exception as e:
        post_error = str(e)
    if posted:
        return json.dumps(
            {
                "ok": True,
                "posted": True,
                "title": artifact.get("title"),
                "symbol": artifact.get("symbol"),
                "hint": "Chart is in Ask. Do not print JSON or the fence.",
            },
            indent=2,
        )
    return json.dumps({"ok": False, "posted": False, "error": post_error}, indent=2)


@server.tool()
async def fmp_news(
    kind: str = "stock",
    symbol: str = "",
    limit: int = 15,
) -> str:
    """Latest FMP headlines. kind=stock or general. optional symbol filter."""
    try:
        client = await _get_engine_client()
        if not client:
            return _err("Engine not available")
        result = await client.call(
            "Gaius",
            "FmpNews",
            {"kind": kind, "symbol": symbol, "limit": limit},
            timeout=30.0,
        )
        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        return _err(str(e))


@server.tool()
async def fmp_search(query: str, limit: int = 8) -> str:
    """FMP name/fragment → tickers. You choose the listing."""
    try:
        client = await _get_engine_client()
        if not client:
            return _err("Engine not available")
        result = await client.call(
            "Gaius",
            "FmpSearch",
            {"query": query, "limit": limit},
            timeout=30.0,
        )
        if isinstance(result, dict) and not result.get("error"):
            result["hint"] = (
                "Pick one symbol from items. Next: fmp_employees / fmp_news / "
                "ask_present. Do not call fmp_search again for the same query."
            )
        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        return _err(str(e))


@server.tool()
async def fmp_employees(symbol: str, limit: int = 16) -> str:
    """Historical employee counts by SEC period. symbol required (from fmp_search)."""
    try:
        client = await _get_engine_client()
        if not client:
            return _err("Engine not available")
        result = await client.call(
            "Gaius",
            "FmpEmployees",
            {"symbol": symbol, "limit": limit},
            timeout=30.0,
        )
        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        return _err(str(e))


@server.tool()
async def theta_sitrep(horizon: str = "day") -> str:
    """Gaius situational report."""
    try:
        client = await _get_engine_client()
        if not client:
            return _err("Engine not available")
        result = await client.call(
            "Gaius", "ThetaSitrep", {"horizon": horizon}, timeout=60.0
        )
        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        return _err(str(e))


@server.tool()
async def orchestrator_status() -> str:
    """GPU / thinking endpoint status."""
    try:
        client = await _get_engine_client()
        if not client:
            return _err("Engine not available")
        result = await client.call("Orchestrator", "status", {}, timeout=15.0)
        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        return _err(str(e))


@server.tool()
async def prospects_status() -> str:
    """Prospects / FMP product status."""
    try:
        client = await _get_engine_client()
        if not client:
            return _err("Engine not available")
        result = await client.call(
            "Prospects", "status", {}, timeout=15.0
        )
        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        return _err(str(e))


@server.tool()
async def agenda_list() -> str:
    """Agenda cards."""
    try:
        client = await _get_engine_client()
        if not client:
            return _err("Engine not available")
        result = await client.call("Gaius", "AgendaList", {}, timeout=15.0)
        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        return _err(str(e))


@server.tool()
async def get_recent_thoughts(limit: int = 10) -> str:
    """Recent cognition thoughts."""
    try:
        from gaius.agents.cognition import get_cognition_agent

        agent = get_cognition_agent()
        thoughts = await agent.get_active_thoughts(limit=limit)
        return json.dumps(
            {
                "count": len(thoughts),
                "thoughts": [t.to_dict() for t in thoughts],
            },
            indent=2,
            default=str,
        )
    except Exception as e:
        return _err(str(e))


def main() -> None:
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
