"""Polite arXiv access: RSS-first, circuit, cache, no headerless-429 retry."""
from __future__ import annotations

import asyncio
import pytest

from gaius.flows.article_curation.arxiv_client import (
    USER_AGENT,
    cap_max_results,
    query_url,
    arxiv_get,
)


def test_query_url_is_get_and_caps_page_size():
    url = query_url({"search_query": "cat:cs.AI", "max_results": 100, "start": 0})
    assert url.startswith("https://export.arxiv.org/api/query?")
    assert "max_results=25" in url
    assert "100" not in url
    assert cap_max_results(3) == 3
    assert cap_max_results(0) == 1


def test_user_agent_is_descriptive():
    assert "Gaius" in USER_AGENT
    assert "github.com/zndx/gaius" in USER_AGENT


class _Resp:
    def __init__(self, status, headers=None, text="<feed/>"):
        self.status_code = status
        self.headers = headers or {}
        self.text = text


def test_arxiv_get_retries_429_with_retry_after_then_succeeds(monkeypatch):
    calls: list[str] = []

    class _Client:
        def __init__(self, *a, **k):
            self.headers = k.get("headers") or {}

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return None

        async def get(self, url):
            calls.append(url)
            if len(calls) < 2:
                return _Resp(429, {"Retry-After": "1"})
            return _Resp(200)

    monkeypatch.setattr(
        "gaius.flows.article_curation.arxiv_client.httpx.AsyncClient",
        _Client,
    )
    monkeypatch.setattr(
        "gaius.flows.article_curation.arxiv_client.robots_allows_api",
        lambda: True,
    )
    monkeypatch.setattr(
        "gaius.flows.article_curation.arxiv_client.MIN_INTERVAL_S",
        0.0,
    )

    url = query_url({"search_query": "all:test", "max_results": 5})
    resp = asyncio.run(arxiv_get(url))
    assert resp.status_code == 200
    assert len(calls) == 2
    assert calls[0].startswith("https://export.arxiv.org/api/query?")


def test_arxiv_get_does_not_retry_429_without_retry_after(arxiv_cache, monkeypatch):
    calls: list[str] = []

    class _Client:
        def __init__(self, *a, **k):
            self.headers = k.get("headers") or {}

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return None

        async def get(self, url):
            calls.append(url)
            return _Resp(429, {})

    monkeypatch.setattr(
        "gaius.flows.article_curation.arxiv_client.httpx.AsyncClient",
        _Client,
    )
    monkeypatch.setattr(
        "gaius.flows.article_curation.arxiv_client.robots_allows_api",
        lambda: True,
    )
    monkeypatch.setattr(
        "gaius.flows.article_curation.arxiv_client.MIN_INTERVAL_S",
        0.0,
    )

    url = query_url({"search_query": "all:test", "max_results": 5})
    with pytest.raises(RuntimeError, match="no Retry-After"):
        asyncio.run(arxiv_get(url))
    assert len(calls) == 1


RSS = b"""<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <item>
      <title>Attention Is All You Need</title>
      <link>https://arxiv.org/abs/1706.03762</link>
      <description>Transformer architecture for sequence transduction.</description>
      <guid>https://arxiv.org/abs/1706.03762</guid>
    </item>
    <item>
      <title>Unrelated Number Theory Paper</title>
      <link>https://arxiv.org/abs/2601.00001</link>
      <description>Primes and sieves.</description>
      <guid>https://arxiv.org/abs/2601.00001</guid>
    </item>
  </channel>
</rss>
"""


@pytest.fixture
def arxiv_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("GAIUS_ARXIV_CACHE", str(tmp_path))
    return tmp_path


def test_rss_url_and_parse():
    from gaius.flows.article_curation.arxiv_client import parse_feed, rss_url

    assert rss_url("cs.LG") == "https://rss.arxiv.org/rss/cs.LG"
    papers = parse_feed(RSS, via="rss")
    assert [p.arxiv_id for p in papers] == ["1706.03762", "2601.00001"]


def test_discover_uses_rss_not_search(arxiv_cache, monkeypatch):
    from gaius.flows.article_curation import arxiv_client as ac

    gets: list[str] = []

    async def fake_get(url, *, timeout=30.0):
        gets.append(url)
        return ac._CachedResp(RSS, url)

    monkeypatch.setattr(ac, "arxiv_get", fake_get)
    papers = asyncio.run(ac.discover_papers(["cs.LG"], keywords=["transformer"], max_results=10))
    assert gets == ["https://rss.arxiv.org/rss/cs.LG"]
    assert not any("export.arxiv.org" in u for u in gets)
    assert papers[0].arxiv_id == "1706.03762"
    assert papers[0].via == "rss"


def test_empty_rss_does_not_clobber_stale(arxiv_cache, monkeypatch):
    from gaius.flows.article_curation import arxiv_client as ac

    url = ac.rss_url("cs.LG")
    ac._write_cache(url, RSS)
    monkeypatch.setattr(ac, "RSS_TTL_S", -1)  # force re-GET
    empty = b"""<?xml version="1.0"?><rss version="2.0"><channel>
      <title>cs.LG</title><skipDays><day>Sunday</day></skipDays>
    </channel></rss>"""

    async def fake_get(url, *, timeout=30.0):
        return ac._CachedResp(empty, url)

    monkeypatch.setattr(ac, "arxiv_get", fake_get)
    papers = asyncio.run(ac.discover_papers(["cs.LG"], max_results=10))
    assert papers[0].arxiv_id == "1706.03762"


def test_headerless_429_opens_circuit(arxiv_cache, monkeypatch):
    from gaius.flows.article_curation.arxiv_client import (
        circuit_blocked,
        query_url,
        arxiv_get,
    )

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return None

        async def get(self, url):
            return _Resp(429, {})

    monkeypatch.setattr(
        "gaius.flows.article_curation.arxiv_client.httpx.AsyncClient",
        _Client,
    )
    monkeypatch.setattr(
        "gaius.flows.article_curation.arxiv_client.MIN_INTERVAL_S",
        0.0,
    )
    url = query_url({"id_list": "1706.03762", "max_results": 1})
    with pytest.raises(RuntimeError, match="circuit open"):
        asyncio.run(arxiv_get(url))
    assert circuit_blocked() is True


def test_stale_cache_serves_while_circuit_open(arxiv_cache, monkeypatch):
    from gaius.flows.article_curation import arxiv_client as ac

    url = ac.rss_url("cs.LG")
    ac._write_cache(url, RSS)
    ac.open_circuit(seconds=60)
    resp = asyncio.run(ac.cached_get(url, ttl_s=1e-9))  # ttl expired, stale OK
    papers = ac.parse_feed(resp.content, via="rss")
    assert papers[0].arxiv_id == "1706.03762"
