"""Serialized arXiv GET: backoff, GET-only, User-Agent, capped pages."""
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


def test_arxiv_get_does_not_retry_429_without_retry_after(monkeypatch):
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
