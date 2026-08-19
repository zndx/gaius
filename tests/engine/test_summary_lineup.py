"""Summary lineup: temporal index, hop, local fork."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from gaius.engine.services.summary_lineup import (
    SummaryLineupError,
    build_index,
    extract_links,
    fork_local,
    get_note,
    load_db_thought,
    parse_thought_id,
    resolve_hop,
    validate_lens,
    validate_section,
)
from gaius.engine.services.weekly_signals_summary import write_zettel


def _kb(tmp: Path) -> Path:
    kb = tmp / "kb"
    (kb / "scratch" / "2026-08-17").mkdir(parents=True)
    (kb / "current" / "articles" / "keiretsu").mkdir(parents=True)
    (kb / "current" / "projects" / "gaius").mkdir(parents=True)
    (kb / "current" / "heuristics" / "gaius" / "summary").mkdir(parents=True)
    (kb / "current" / "ontology").mkdir(parents=True)
    (kb / "current" / "articles" / "keiretsu" / "article.md").write_text(
        "# AI Keiretsu\n\nSee [[current/ontology/README]] and guru.\n",
        encoding="utf-8",
    )
    (kb / "current" / "projects" / "gaius" / "gaius.md").write_text(
        "# Gaius Project\n\n- [[current/projects/pliny]]\n",
        encoding="utf-8",
    )
    (kb / "current" / "heuristics" / "gaius" / "summary" / "weekly_signals.md").write_text(
        "# Weekly Signals Summary\n\nGuru #WS.00000001.\n",
        encoding="utf-8",
    )
    (kb / "current" / "ontology" / "README.md").write_text(
        "# KB Ontology Directory\n\nOWL loads via DeepOnto.\n",
        encoding="utf-8",
    )
    write_zettel(
        kb,
        "scratch/2026-08-17/2026-08-17-025048_w33-summary.md",
        "# Weekly Signals Summary · 2026-W33\n\n"
        "See [[current/projects/gaius/gaius.md]] and [[current/heuristics/gaius/summary/weekly_signals.md]].\n",
    )
    return kb


def test_validate_section_lens() -> None:
    assert validate_section("Ontology") == "ontology"
    assert validate_section("corpus") == "corpus"
    assert validate_lens("THOUGHTS") == "thoughts"
    with pytest.raises(SummaryLineupError, match="WS.00000005"):
        validate_section("archive")
    with pytest.raises(SummaryLineupError, match="WS.00000006"):
        validate_lens("week")


def test_parse_corpus_id() -> None:
    from gaius.engine.services.summary_corpus import parse_corpus_id

    assert parse_corpus_id("lens/corpus") == ("seed", "")
    assert parse_corpus_id("corpus/item/12") == ("item", "12")
    assert parse_corpus_id("corpus/inflow/44") == ("inflow", "44")
    assert parse_corpus_id("thought/abc") == ("", "")


def test_corpus_seed_body_names_admission() -> None:
    from gaius.engine.services.summary_corpus import _seed_body

    body = _seed_body(
        n_items=4,
        n_sources=3,
        first=None,
        last=None,
        mix=[("DATAENG", 2), ("UTILITY", 2)],
        n_act=4,
        n_feat=80,
        n_minted=3,
        recent=[(1, "Replay", "DATAENG", "Replay 26")],
        strategy_id="test-strategy",
        tau=0.1,
        grain=512,
        collection="sdg_aperture",
    )
    assert "Corpus" in body
    assert "admitted 512-token" in body
    assert "[[corpus/item/1|Replay]]" in body
    assert "MaxSim" in body


def test_inflow_body_includes_extracted_text() -> None:
    from gaius.engine.services.summary_corpus import _inflow_body

    body = _inflow_body(
        cid="12",
        title="Replay",
        url="https://example.test",
        source="temporal_blog",
        origin="kb:current/content/x.md",
        extracted="# Replay\n\nThe complete extracted article body.",
        windows=[(1, "DATAENG", "Replay 26")],
    )
    assert "complete extracted article body" in body
    assert "extracted_from" in body
    assert "kb:current/content/x.md" in body
    assert "[[corpus/item/1|Replay 26]]" in body


def test_extract_links() -> None:
    assert extract_links("See [[current/a]] and [[b|label]].") == [
        "current/a",
        "b",
    ]


@pytest.mark.asyncio
async def test_index_week_landing_and_linked(tmp_path: Path) -> None:
    kb = _kb(tmp_path)
    idx = await build_index(kb, week="2026-W33", section="", lens="")
    assert idx["week"] == "2026-W33"
    assert idx["landing_id"].endswith("_w33-summary.md")
    seed = idx["seed"]
    assert seed.virtual
    ids = {n.id for n in idx["items"]}
    assert "current/projects/gaius/gaius.md" in ids
    assert "current/heuristics/gaius/summary/weekly_signals.md" in ids


@pytest.mark.asyncio
async def test_articles_lens_lists_kb_folder(tmp_path: Path) -> None:
    from gaius.engine.services.knowledge_summary import write_section_summary

    kb = _kb(tmp_path)
    write_section_summary(kb, "articles", week="2026-W01")
    idx = await build_index(kb, week="2026-W01", section="", lens="articles")
    ids = {n.id for n in idx["items"]}
    assert "current/articles/keiretsu/article.md" in ids
    assert idx["landing_id"] == "current/articles/summary.md"
    assert idx["seed"].title == "Articles"
    assert "· Articles" not in idx["seed"].title


@pytest.mark.asyncio
async def test_section_ignores_lens_intersection(tmp_path: Path) -> None:
    """KNOWLEDGE is a collection, not a filter on Articles."""
    kb = _kb(tmp_path)
    idx = await build_index(kb, week="2026-W33", section="heuristic", lens="articles")
    assert idx["seed"].title == "Heuristics"
    assert "· Articles" not in idx["seed"].title
    assert idx["seed"].lens == "knowledge"
    ids = {n.id for n in idx["items"]}
    assert "current/heuristics/gaius/summary/weekly_signals.md" in ids
    assert "current/articles/keiretsu/article.md" not in ids


@pytest.mark.asyncio
async def test_ontology_section_lists_kb_folder(tmp_path: Path) -> None:
    kb = _kb(tmp_path)
    idx = await build_index(kb, week="2026-W01", section="ontology", lens="")
    ids = {n.id for n in idx["items"]}
    assert "current/ontology/README.md" in ids
    assert idx["seed"].virtual
    assert "[[current/ontology/README.md" in idx["seed"].body


@pytest.mark.asyncio
async def test_heuristic_section_lists_kb_folder(tmp_path: Path) -> None:
    from gaius.engine.services.knowledge_summary import run_knowledge_summaries

    kb = _kb(tmp_path)
    written = run_knowledge_summaries(kb=kb, week="2026-W33", section="heuristic")
    assert written[0].path == "current/heuristics/summary.md"
    idx = await build_index(kb, week="2026-W01", section="heuristic", lens="")
    ids = {n.id for n in idx["items"]}
    assert "current/heuristics/gaius/summary/weekly_signals.md" in ids
    assert "current/heuristics/summary.md" not in ids
    assert idx["landing_id"] == "current/heuristics/summary.md"
    assert not idx["seed"].virtual
    assert "[[current/heuristics/gaius/summary/weekly_signals.md" in idx["seed"].body


@pytest.mark.asyncio
async def test_hop_and_fork(tmp_path: Path) -> None:
    kb = _kb(tmp_path)
    resolved = resolve_hop(kb, "lens/week", "current/ontology/README")
    assert resolved.endswith("ontology/README.md")
    note = get_note(kb, resolved, week="2026-W33")
    assert "DeepOnto" in note.body
    now = datetime(2026, 8, 17, 12, 0, 0, tzinfo=timezone.utc)
    forked = fork_local(kb, note, now=now)
    assert forked.id.startswith("scratch/2026-08-17/")
    assert "fork-" in forked.id
    assert "origin_id: current/ontology/README.md" in forked.body
    with pytest.raises(SummaryLineupError, match="WS.00000007"):
        resolve_hop(kb, "", "does-not-exist-xyz")


def test_parse_thought_id() -> None:
    uid = "3633050f-a1a2-4fd7-b52f-2c495f0dcc65"
    assert parse_thought_id(f"thought/{uid}") == uid
    assert parse_thought_id(uid.upper()) == uid
    assert parse_thought_id("scratch/x.md") == ""


@pytest.mark.asyncio
async def test_load_db_thought_body() -> None:
    uid = "3633050f-a1a2-4fd7-b52f-2c495f0dcc65"
    row = {
        "id": uid,
        "thought_type": "curiosity",
        "title": "Are Negative Results Undervalued in AI Research?",
        "summary": "",
        "content": "The NVIDIA B300 report highlights negative results.",
        "salience": 0.7,
        "generation": 1,
        "note_path": "scratch/2026-08-15/132501_thoughts_cycle.md",
        "created_at": datetime(2026, 8, 15, 13, 25, 1, tzinfo=timezone.utc),
    }

    class _Conn:
        async def fetchrow(self, _sql: str, *_a: object) -> object:
            return row

    class _Acquire:
        def __init__(self, conn: _Conn) -> None:
            self._conn = conn

        async def __aenter__(self) -> _Conn:
            return self._conn

        async def __aexit__(self, *_a: object) -> None:
            return None

    class _Pool:
        def acquire(self) -> _Acquire:
            return _Acquire(_Conn())

    note = await load_db_thought(_Pool(), f"thought/{uid}", week="2026-W33")
    assert note.id == f"thought/{uid}"
    assert note.lens == "thoughts"
    assert note.virtual
    assert "negative results" in note.body.lower()
    assert "scratch/2026-08-15/132501_thoughts_cycle.md" in note.links


@pytest.mark.asyncio
async def test_load_db_thought_missing() -> None:
    class _Conn:
        async def fetchrow(self, _sql: str, *_a: object) -> object:
            return None

    class _Acquire:
        def __init__(self, conn: _Conn) -> None:
            self._conn = conn

        async def __aenter__(self) -> _Conn:
            return self._conn

        async def __aexit__(self, *_a: object) -> None:
            return None

    class _Pool:
        def acquire(self) -> _Acquire:
            return _Acquire(_Conn())

    with pytest.raises(SummaryLineupError, match="WS.00000014"):
        await load_db_thought(_Pool(), "thought/3633050f-a1a2-4fd7-b52f-2c495f0dcc65")
