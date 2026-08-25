"""Ask rich-present: OHLC / table / links / markdown.

Engine-first. Façade and MCP call AskPresent; this module talks to FMP
and returns the artifact JSON. It does not wait on vLLM.
"""

from __future__ import annotations

import json
from typing import Any

from gaius.engine.services.fmp_client import get_fmp_client

GURU_BADARTIFACT = (
    "Ask present payload is invalid.\n"
    "  Guru: #UI.00000007.BADARTIFACT"
)
GURU_NOBARS = (
    "ohlc needs bars or a symbol with FMP history.\n"
    "  Guru: #UI.00000008.NOBARS"
)
GURU_INFRA = (
    "ohlc symbol is an infra token, not a ticker.\n"
    "  Guru: #UI.00000009.INFRAOHLC\n"
    "  Use /chart $TICKER or $NVDA. ROOT/HTML/YK are not charts."
)
_INFRA_TICKERS = frozenset(
    {
        "ROOT",
        "HTML",
        "HTTP",
        "JSON",
        "GPU",
        "GPUS",
        "CLI",
        "TUI",
        "UTC",
        "ISO",
        "SQL",
        "API",
        "MCP",
        "SAE",
        "CLT",
        "SKOS",
        "YK",
        "GAIUS",
        "QUEUE",
        "PAGE",
        "FOCUS",
        "CLOCK",
        "BOARD",
        "GRID",
    }
)


class AskPresentError(RuntimeError):
    """Fail-fast present error with guru in the message."""


def _looks_like_ticker(symbol: str) -> bool:
    s = (symbol or "").strip()
    return 1 <= len(s) <= 5 and s.isalpha()


def _parse_list(raw: str, what: str) -> list[Any]:
    text = (raw or "").strip()
    if not text:
        return []
    loaded = json.loads(text)
    if not isinstance(loaded, list):
        raise AskPresentError(f"{GURU_BADARTIFACT}\n  {what} must be a JSON array.")
    return loaded


async def build_artifact(
    *,
    kind: str = "ohlc",
    symbol: str = "",
    title: str = "",
    from_date: str = "",
    to_date: str = "",
    payload_json: str = "",
) -> dict[str, Any]:
    kind = (kind or "ohlc").strip().lower()
    if kind in ("link", "url"):
        kind = "links"
    artifact: dict[str, Any] = {
        "type": kind,
        "title": (title or "").strip(),
        "symbol": (symbol or "").strip().upper(),
    }
    if kind == "ohlc":
        parsed = _parse_list(payload_json, "bars")
        if artifact["symbol"] in _INFRA_TICKERS and not parsed:
            raise AskPresentError(GURU_INFRA)
        if not parsed and artifact["symbol"]:
            client = await get_fmp_client()
            try:
                raw_sym = artifact["symbol"]
                if not _looks_like_ticker(raw_sym):
                    hits = await client.search_ticker(raw_sym)
                    if not hits:
                        raise AskPresentError(
                            f"No ticker for {raw_sym!r}.\n"
                            "  Guru: #UI.00000011.NOSYMBOL\n"
                            "  Use /chart $TICKER if you know the symbol."
                        )
                    artifact["symbol"] = hits[0]["symbol"]
                    if not artifact["title"]:
                        artifact["title"] = hits[0].get("name") or artifact["symbol"]
                if artifact["symbol"] in _INFRA_TICKERS:
                    raise AskPresentError(GURU_INFRA)
                parsed = await client.get_historical_eod(
                    artifact["symbol"],
                    from_date=from_date or None,
                    to_date=to_date or None,
                    source_context={"source": "ask_present"},
                )
            finally:
                await client.__aexit__(None, None, None)
        if not parsed:
            raise AskPresentError(GURU_NOBARS)
        artifact["bars"] = parsed
        if not artifact["title"]:
            artifact["title"] = artifact["symbol"] or "OHLC"
        return artifact
    if kind == "markdown":
        artifact["body"] = payload_json
        return artifact
    if kind == "table":
        rows = _parse_list(payload_json, "table rows")
        if not rows:
            raise AskPresentError(f"{GURU_BADARTIFACT}\n  table needs rows JSON.")
        artifact["rows"] = rows
        if not artifact["title"]:
            artifact["title"] = "Table"
        return artifact
    if kind == "links":
        links = _parse_list(payload_json, "links")
        if not links:
            raise AskPresentError(f"{GURU_BADARTIFACT}\n  links needs [{{href,title}}].")
        artifact["links"] = links
        if not artifact["title"]:
            artifact["title"] = "Links"
        return artifact
    raise AskPresentError(
        f"{GURU_BADARTIFACT}\n  kind must be ohlc, table, links, or markdown."
    )
