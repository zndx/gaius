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


class AskPresentError(RuntimeError):
    """Fail-fast present error with guru in the message."""


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
        if not parsed and artifact["symbol"]:
            client = await get_fmp_client()
            try:
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
