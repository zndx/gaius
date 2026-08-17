"""AskPresent builds artifacts without vLLM."""

from __future__ import annotations

import json

import pytest

from gaius.engine.services.ask_present import AskPresentError, build_artifact


@pytest.mark.asyncio
async def test_table_and_links() -> None:
    table = await build_artifact(
        kind="table",
        payload_json=json.dumps([{"gpu": 4, "model": "1.7B"}]),
    )
    assert table["type"] == "table"
    assert table["rows"][0]["gpu"] == 4
    links = await build_artifact(
        kind="links",
        payload_json=json.dumps([{"href": "http://127.0.0.1:9889", "title": "Signals"}]),
    )
    assert links["links"][0]["title"] == "Signals"


@pytest.mark.asyncio
async def test_ohlc_needs_symbol_or_bars() -> None:
    with pytest.raises(AskPresentError, match="UI.00000008"):
        await build_artifact(kind="ohlc")
