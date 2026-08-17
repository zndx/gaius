"""KNOWLEDGE collection summaries: wiki hops, no self-include."""

from __future__ import annotations

from pathlib import Path

import pytest

from gaius.engine.services.knowledge_summary import (
    KnowledgeSummaryError,
    list_section_notes,
    render_section,
    run_knowledge_summaries,
    write_section_summary,
)
from gaius.engine.services.summary_lineup import extract_links
from gaius.engine.services.weekly_signals_summary import parse_iso_week
from datetime import datetime, timezone


def _kb(tmp: Path) -> Path:
    kb = tmp / "kb"
    (kb / "current" / "ontology" / "topics").mkdir(parents=True)
    (kb / "current" / "heuristics" / "gaius" / "engine").mkdir(parents=True)
    (kb / "current" / "ontology" / "README.md").write_text(
        "# KB Ontology Directory\n\nOWL loads via DeepOnto.\n",
        encoding="utf-8",
    )
    (kb / "current" / "ontology" / "topics" / "verification-process.md").write_text(
        "# Verification Process\n\nA process that validates KB content.\n",
        encoding="utf-8",
    )
    (kb / "current" / "heuristics" / "gaius" / "engine" / "grpc_dual_bind.md").write_text(
        "# Engine gRPC dual-bind\n\nTwo PIDs listen on :50051.\n",
        encoding="utf-8",
    )
    return kb


def test_list_and_render_groups_and_wiki(tmp_path: Path) -> None:
    kb = _kb(tmp_path)
    onto = list_section_notes(kb, "ontology")
    assert {n.id for n in onto} == {
        "current/ontology/README.md",
        "current/ontology/topics/verification-process.md",
    }
    cats = {n.id: n.category for n in onto}
    assert cats["current/ontology/README.md"] == "index"
    assert cats["current/ontology/topics/verification-process.md"] == "topics"
    now = datetime(2026, 8, 17, 12, 0, tzinfo=timezone.utc)
    body = render_section("ontology", onto, week="2026-W34", now=now)
    assert "## Index" in body
    assert "## topics" in body
    assert "[[current/ontology/README.md|KB Ontology Directory]]" in body
    assert "[[current/ontology/topics/verification-process.md|Verification Process]]" in body
    assert "wiki" not in extract_links(body)


def test_write_skips_generated_summary(tmp_path: Path) -> None:
    kb = _kb(tmp_path)
    first = write_section_summary(kb, "heuristic", week="2026-W34")
    assert first.path == "current/heuristics/summary.md"
    assert first.notes == 1
    assert "[[current/heuristics/gaius/engine/grpc_dual_bind.md|" in first.body
    again = list_section_notes(kb, "heuristic")
    assert all(n.id != "current/heuristics/summary.md" for n in again)
    both = [
        write_section_summary(kb, "ontology", week="2026-W34"),
        write_section_summary(kb, "heuristic", week="2026-W34"),
    ]
    assert {w.path for w in both} == {
        "current/ontology/summary.md",
        "current/heuristics/summary.md",
    }


def test_missing_section_fails_fast(tmp_path: Path) -> None:
    kb = tmp_path / "empty"
    kb.mkdir()
    (kb / "current").mkdir()
    with pytest.raises(KnowledgeSummaryError, match="WS.00000012"):
        list_section_notes(kb, "ontology")


def test_bad_section() -> None:
    with pytest.raises(KnowledgeSummaryError, match="WS.00000005"):
        list_section_notes(Path("/tmp"), "archive")


def test_articles_and_projects_catalog(tmp_path: Path) -> None:
    kb = _kb(tmp_path)
    (kb / "current" / "articles" / "keiretsu").mkdir(parents=True)
    (kb / "current" / "articles" / "keiretsu" / "article.md").write_text(
        "# AI Keiretsu\n\nAutonomous economic networks.\n",
        encoding="utf-8",
    )
    (kb / "current" / "articles" / "keiretsu" / "zk").mkdir()
    (kb / "current" / "articles" / "keiretsu" / "zk" / "seed.md").write_text(
        "# should not be a trailhead\n",
        encoding="utf-8",
    )
    (kb / "current" / "projects").mkdir(parents=True)
    (kb / "current" / "projects" / "gaius.md").write_text(
        "# Gaius\n\nCLI-first TUI.\n",
        encoding="utf-8",
    )
    arts = list_section_notes(kb, "articles")
    assert [n.id for n in arts] == ["current/articles/keiretsu/article.md"]
    written = write_section_summary(kb, "articles", week="2026-W34")
    assert written.path == "current/articles/summary.md"
    assert "[[current/articles/keiretsu/article.md|AI Keiretsu]]" in written.body
    assert "zk/seed" not in written.body
    proj = write_section_summary(kb, "projects", week="2026-W34")
    assert "[[current/projects/gaius.md|Gaius]]" in proj.body


def test_thoughts_from_week_scratch(tmp_path: Path) -> None:
    kb = _kb(tmp_path)
    day = kb / "scratch" / "2026-08-17"
    day.mkdir(parents=True)
    (day / "2026-08-17-130000_watchlist-after-q2-13f.md").write_text(
        "# Watchlist after Q2 13F\n\nNames that moved.\n",
        encoding="utf-8",
    )
    (day / "2026-08-17-024851_w34-summary.md").write_text(
        "# Weekly Signals Summary · 2026-W34\n\nskip me\n",
        encoding="utf-8",
    )
    notes = list_section_notes(kb, "thoughts", week="2026-W34")
    assert [n.id for n in notes] == [
        "scratch/2026-08-17/2026-08-17-130000_watchlist-after-q2-13f.md"
    ]
    written = write_section_summary(kb, "thoughts", week="2026-W34")
    assert written.path == "current/thoughts/summary.md"
    assert "[[scratch/2026-08-17/2026-08-17-130000_watchlist-after-q2-13f.md|" in written.body
    assert "w34-summary" not in written.body
    assert (kb / "current" / "thoughts" / "summary.md").is_file()


def test_week_stamp_parse() -> None:
    window = parse_iso_week("2026-W34")
    assert window.label == "2026-W34"


def test_flow_registers() -> None:
    from gaius.flows import FLOW_REGISTRY
    from gaius.flows.summary import KnowledgeSummaryFlow

    assert FLOW_REGISTRY.get("knowledge-summary") is KnowledgeSummaryFlow
