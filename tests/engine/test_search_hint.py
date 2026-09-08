"""ServerQuery SEARCH: honest empty query; kb/web streams."""
from __future__ import annotations

import pytest

from gaius.engine.services.search_hint import collect_search, to_proto


@pytest.mark.asyncio
async def test_empty_query_is_honest():
    d = await collect_search("")
    assert d["hits"] == []
    assert d["note"] == "empty query"


@pytest.mark.asyncio
async def test_kb_stream_maps_search_kb(monkeypatch):
    class _R:
        def __init__(self, path, preview, match_type="content"):
            self.path = path
            self.preview = preview
            self.match_type = match_type

    async def _kb(query, max_results=10):
        assert query == "theta"
        return [_R("scratch/2026-09-07/theta.md", "NVAR drift vs sitrep")]

    monkeypatch.setattr("gaius.storage.kb_ops.search_kb", _kb)
    d = await collect_search("theta", stream="kb", limit=4)
    assert d["stream"] == "kb"
    assert d["hits"][0]["source"] == "kb"
    assert d["hits"][0]["url"] == "scratch/2026-09-07/theta.md"
    hint = to_proto(d)
    assert hint.hits[0].source == "kb"


@pytest.mark.asyncio
async def test_web_without_key_notes_honestly(monkeypatch):
    monkeypatch.delenv("BRAVE_API_KEY", raising=False)
    monkeypatch.delenv("BRAVE_SEARCH_API_KEY", raising=False)
    d = await collect_search("intel 18A", stream="web")
    assert d["hits"] == []
    assert "Brave" in d["note"]
