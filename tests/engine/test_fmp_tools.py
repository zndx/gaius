"""FMP proxy catalog — engine SoR for MCP / CLI / AgentRTC."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from gaius.engine.services.fmp_tools import BY_NAME, call_tool, list_tools


def test_form_key_normalizes_eight_k():
    from gaius.engine.services.fmp_client import _form_key

    assert _form_key("8-K") == _form_key("8K") == "8K"
    assert _form_key("Form 4") == "FORM4" or _form_key("4") == "4"


def test_catalog_names_are_starter_legal():
    names = {t["name"] for t in list_tools()}
    assert "fmp_search" in names
    assert "fmp_filings" in names
    assert "fmp_statement" in names
    assert "fmp_13f" not in names
    assert "fmp_transcript" not in names
    assert set(BY_NAME) >= {"search", "quote", "news", "filings", "8k", "profile", "eod"}
    assert BY_NAME["profile"] is not BY_NAME["quote"]


@pytest.mark.asyncio
async def test_unknown_tool_is_honest():
    d = await call_tool("transcripts", {"symbol": "AAPL"})
    assert d["ok"] is False
    assert "unknown" in d["error"]


@pytest.mark.asyncio
async def test_call_search_uses_client(monkeypatch):
    class _C:
        async def search_ticker(self, q, limit=8):
            return [{"symbol": "AAPL", "name": "Apple", "exchange": "NASDAQ"}]

        async def __aexit__(self, *a):
            return None

    async def _client():
        return _C()

    monkeypatch.setattr("gaius.engine.services.fmp_tools.get_fmp_client", _client)
    d = await call_tool("fmp_search", {"query": "apple"})
    assert d["ok"] is True
    assert d["items"][0]["symbol"] == "AAPL"
