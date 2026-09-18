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

    async def get_quote(self, q):
        return {
            "symbol": "SLB",
            "name": "Schlumberger Limited",
            "price": 38.5,
            "change": 0.4,
            "changesPercentage": 1.05,
            "volume": 1_000_000,
            "exchange": "NYSE",
        }

    async def get_stock_news(self, q, limit=12):
        return await self.get_latest_stock_news(limit=limit)

    async def get_sec_filings(self, q, filing_type=None, limit=8, from_date=None, to_date=None):
        return [
            SimpleNamespace(
                symbol="SLB",
                filing_type="8-K",
                filing_date="2026-08-31",
                accepted_date="2026-08-31",
                final_link="https://www.sec.gov/Archives/edgar/data/87347/8k.htm",
            )
        ]

    async def get_insider_trades(self, q, limit=15):
        return [
            {
                "symbol": "SLB",
                "reportingName": "CEO",
                "transactionType": "S-Sale",
                "securitiesTransacted": 1000,
                "price": 38.0,
                "transactionDate": "2026-09-01",
            }
        ]

    async def __aexit__(self, *a):
        return None


@pytest.mark.asyncio
async def test_search_stream_returns_tickers(monkeypatch):
    async def _client():
        return _Client()

    monkeypatch.setattr("gaius.engine.services.fmp_tools.get_fmp_client", _client)
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

    monkeypatch.setattr("gaius.engine.services.fmp_tools.get_fmp_client", _client)
    d = await collect_fmp("SLB", stream="quote")
    assert d["hits"][0]["source"] == "quote"
    assert "38.5" in d["hits"][0]["snippet"] or "px=38.5" in d["hits"][0]["snippet"]
    assert "FMP quote" in d["spoken"]


@pytest.mark.asyncio
async def test_eight_k_is_per_symbol_sec_search(monkeypatch):
    async def _client():
        return _Client()

    monkeypatch.setattr("gaius.engine.services.fmp_tools.get_fmp_client", _client)
    d = await collect_fmp("SLB", stream="eight_k")
    assert d["hits"]
    assert d["hits"][0]["as_of"].startswith("2026-08-31")
    assert "8-K" in d["hits"][0]["title"]


@pytest.mark.asyncio
async def test_news_and_insider_are_per_symbol(monkeypatch):
    async def _client():
        return _Client()

    monkeypatch.setattr("gaius.engine.services.fmp_tools.get_fmp_client", _client)
    news = await collect_fmp("SLB", stream="news")
    assert news["hits"][0]["symbol"] == "SLB"
    assert "Gulf" in news["hits"][0]["title"]
    insider = await collect_fmp("SLB", stream="insider")
    assert insider["hits"][0]["symbol"] == "SLB"
    assert "CEO" in insider["hits"][0]["title"]
