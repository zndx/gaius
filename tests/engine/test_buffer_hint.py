"""Dual-cognition glance: AST upper buffer plus HN/FMP FIFO entropy."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from gaius.engine.services.ambient_buffer import BufferEntry, BufferRole
from gaius.engine.services.buffer_hint import collect_buffer
from gaius.engine.services.search_hint import collect_search


class _Fifo:
    def __init__(self, entries: list[BufferEntry]) -> None:
        self._entries = entries

    async def snapshot(self) -> list[BufferEntry]:
        return list(self._entries)


def _entry(title: str, body: str, url: str = "") -> BufferEntry:
    return BufferEntry.create(
        BufferRole.CONTENT,
        body,
        source_url=url,
        metadata={"story_title": title},
    )


class _Schema:
    def succinct(self, *, max_items: int = 8, excerpt: int = 180):
        return [
            {
                "flag": "ADMIT",
                "stream": "prospects",
                "role": "fmp",
                "source_id": "slb",
                "code": "SDG.ICE",
                "excerpt": "SLB 10-K liquidity",
            }
        ][:max_items]


@pytest.mark.asyncio
async def test_empty_services_are_honest() -> None:
    d = await collect_buffer(None, stream="buffer")
    assert d["hits"] == []
    assert "empty" in d["note"]
    assert d["spoken"] == ""


@pytest.mark.asyncio
async def test_buffer_stream_leads_with_ast_then_hn_and_fmp() -> None:
    hn = _Fifo(
        [_entry("Show HN: aperture", "A ColBERT membrane for harvest", "https://news.ycombinator.com/1")]
    )
    fmp = _Fifo([_entry("SLB", "liquidity covenant in the 10-K", "")])
    services = SimpleNamespace(
        ambient_service=SimpleNamespace(_buffer=hn),
        prospects_service=SimpleNamespace(_buffer=fmp),
        cognition_buffer=_Schema(),
    )
    d = await collect_buffer(services, stream="buffer", limit=4)
    sources = [h["source"] for h in d["hits"]]
    assert sources[0] == "attention"
    assert "hn" in sources and "fmp" in sources
    assert "Attending" in d["spoken"]
    assert "HN:" in d["spoken"] and "FMP:" in d["spoken"]
    assert d["note"] == d["spoken"]


@pytest.mark.asyncio
async def test_search_hn_stream_skips_empty_query(monkeypatch) -> None:
    hn = _Fifo([_entry("Ask HN: GPUs", "who has spare H100s", "")])
    services = SimpleNamespace(
        ambient_service=SimpleNamespace(_buffer=hn),
        prospects_service=None,
        cognition_buffer=None,
    )
    d = await collect_search("", stream="hn", services=services)
    assert d["stream"] == "hn"
    assert d["hits"][0]["source"] == "hn"
    assert d["hits"][0]["title"] == "Ask HN: GPUs"
