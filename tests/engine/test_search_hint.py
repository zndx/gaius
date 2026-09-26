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


def test_extra_words_still_find_the_published_source():
    """The question may add words the note never used. The title still hits."""
    from gaius.storage.kb_ops import rank_documents

    docs = [
        (
            "scratch/2026-09-25/thoughts.md",
            "durable state and a Nakamoto consensus paper in the same breath",
        ),
        (
            "current/content/arxiv/084500_security-limits-of-mining-before-validation-in-nakamoto-cons.md",
            "# Security Limits of Mining Before Validation in Nakamoto Consensus\n\n"
            "Mining before validation allows miners to extend a newly received block.",
        ),
    ]
    rows = rank_documents(
        docs,
        "gaius.zndx.org Nakamoto consensus durable state",
        4,
    )
    assert rows
    assert rows[0].path.endswith("nakamoto-cons.md")
    assert rows[0].match_type == "filename"


@pytest.mark.asyncio
async def test_published_card_is_a_kb_hit(monkeypatch):
    class _Conn:
        async def fetch(self, _sql, patterns):
            assert any("nakamoto" in p for p in patterns)
            return [
                {
                    "card_id": "card_99d6400a99dc",
                    "title": "State Without a Landlord",
                    "summary": "A peer-to-peer replication proposal.",
                },
                {
                    "card_id": "card_1afddfc7d75f",
                    "title": "Security Limits of Mining Before Validation in Nakamoto Consensus",
                    "summary": "Mining before validation allows miners to extend a newly received block.",
                },
            ]

    class _Pool:
        def acquire(self):
            return self

        async def __aenter__(self):
            return _Conn()

        async def __aexit__(self, *_exc):
            return None

    class _Services:
        db_pool = _Pool()

    async def _kb(query, max_results=10):
        return []

    monkeypatch.setattr("gaius.storage.kb_ops.search_kb", _kb)
    d = await collect_search(
        "gaius.zndx.org Nakamoto consensus durable state",
        stream="kb",
        limit=4,
        services=_Services(),
    )
    assert [h["url"] for h in d["hits"] if h["source"] == "card"] == [
        "https://gaius.zndx.org/cards/card_1afddfc7d75f"
    ]
    assert d["hits"][0]["source"] == "card"
    assert d["hits"][0]["url"] == "https://gaius.zndx.org/cards/card_1afddfc7d75f"
    assert "Nakamoto" in d["hits"][0]["title"]


@pytest.mark.asyncio
async def test_web_without_key_notes_honestly(monkeypatch):
    monkeypatch.delenv("BRAVE_API_KEY", raising=False)
    monkeypatch.delenv("BRAVE_SEARCH_API_KEY", raising=False)
    d = await collect_search("intel 18A", stream="web")
    assert d["hits"] == []
    assert "Brave" in d["note"]
