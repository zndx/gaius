"""Live FMP ServerQuery collector — key stays on Gaius."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from gaius.engine.services.fmp_hint import collect_fmp, to_proto


class _Client:
    async def search_ticker(self, q, limit=8):
        return [{"symbol": "SLB", "name": "Schlumberger", "exchange": "NYSE"}]

    async def get_latest_stock_news(self, limit=15):
        return [
            {
                "symbol": "SLB",
                "title": "SLB wins a Gulf contract",
                "text": "deepwater",
                "url": "https://example.test/slb",
                "publishedDate": "2026-09-09",
            }
        ]

    async def get_company_profile(self, q):
        return SimpleNamespace(
            symbol="SLB",
            company_name="Schlumberger Limited",
            exchange="NYSE",
            sector="Energy",
            industry="Oilfield Services",
            market_cap=60_000_000_000,
            description="oilfield",
            website="https://www.slb.com",
        )

    async def __aexit__(self, *a):
        return None


@pytest.mark.asyncio
async def test_search_stream_returns_tickers(monkeypatch):
    async def _client():
        return _Client()

    monkeypatch.setattr("gaius.engine.services.fmp_hint.get_fmp_client", _client)
    d = await collect_fmp("schlumberger", stream="search")
    assert d["hits"][0]["symbol"] == "SLB"
    assert "FMP tickers" in d["spoken"]
    hint = to_proto(d)
    assert hint.hits[0].symbol == "SLB"


@pytest.mark.asyncio
async def test_empty_search_is_honest():
    d = await collect_fmp("", stream="search")
    assert d["hits"] == []
    assert d["note"] == "empty query"


@pytest.mark.asyncio
async def test_quote_stream(monkeypatch):
    async def _client():
        return _Client()

    monkeypatch.setattr("gaius.engine.services.fmp_hint.get_fmp_client", _client)
    d = await collect_fmp("SLB", stream="quote")
    assert d["hits"][0]["source"] == "quote"
    assert "Energy" in d["hits"][0]["snippet"]
