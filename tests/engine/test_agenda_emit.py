"""Agenda emit: upsert by slug, intent routing, no raise on bad root."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from gaius.engine.services.agenda_emit import (
    backfill_surfaces,
    emit,
    emit_prospects_update,
    emit_publish_cards,
)


def test_emit_rewrites_same_slug(tmp_path: Path) -> None:
    kb = tmp_path / "kb"
    (kb / "scratch").mkdir(parents=True)
    now = datetime(2026, 8, 14, 13, 0, 0, tzinfo=timezone.utc)
    a = emit(
        kind="event",
        title="Q2 13F window vs watchlist",
        body="one\n",
        now=now,
        starts="2026-08-14T13:00:00+00:00",
        intent="session",
        root=kb,
    )
    b = emit(
        kind="event",
        title="Q2 13F window vs watchlist",
        body="two\n",
        now=now,
        starts="2026-08-14T13:00:00+00:00",
        intent="session",
        root=kb,
    )
    assert a is not None and b is not None
    assert a.path == b.path
    assert "two" in b.body
    day = kb / "scratch" / "2026-08-14"
    assert len(list(day.glob("*.md"))) == 1
    assert b.intent == "session"
    assert "calendar.google.com" in (b.calendar_url() or b.body)


def test_publish_skips_zero(tmp_path: Path) -> None:
    kb = tmp_path / "kb"
    (kb / "scratch").mkdir(parents=True)
    assert emit_publish_cards({"published_count": 0}, root=kb) is None
    item = emit_publish_cards(
        {"published_count": 2, "slot": "morning", "kv_sync_success": True},
        root=kb,
    )
    assert item is not None
    assert item.intent == "brief"
    assert "2 card" in item.body


def test_prospects_error_is_reminder(tmp_path: Path) -> None:
    kb = tmp_path / "kb"
    (kb / "scratch").mkdir(parents=True)
    item = emit_prospects_update(
        {"status": "error", "symbols": ["CHTR"], "error": "#YK.00000001.NOADMIT"},
        root=kb,
    )
    assert item is not None
    assert item.intent == "reminder"
    assert item.kind == "list"


def test_prospects_filings_book_session(tmp_path: Path) -> None:
    kb = tmp_path / "kb"
    (kb / "scratch").mkdir(parents=True)
    item = emit_prospects_update(
        {
            "status": "completed",
            "symbols": ["CHTR", "DIS"],
            "new_filings_count": 12,
            "error": "",
        },
        root=kb,
    )
    assert item is not None
    assert item.intent == "session"
    assert item.starts
    assert "CHTR" in item.body


def test_backfill_is_idempotent(tmp_path: Path) -> None:
    kb = tmp_path / "kb"
    (kb / "scratch").mkdir(parents=True)
    first = backfill_surfaces(kb)
    second = backfill_surfaces(kb)
    assert len(first) >= 6
    assert len(second) == len(first)
    paths = {i.path for i in first}
    assert paths == {i.path for i in second}
    titles = {i.title for i in first}
    assert "Q2 13F window vs watchlist" in titles
    assert "Q3 13F window" in titles
    q2 = next(i for i in first if i.title.startswith("Q2"))
    assert q2.intent == "session"
    watch = next(i for i in first if i.title.startswith("Watchlist"))
    assert watch.intent == "reminder"


def test_emit_bad_root_does_not_raise(tmp_path: Path) -> None:
    missing = tmp_path / "nope"
    assert (
        emit(
            kind="note",
            title="x",
            body="y",
            now=datetime(2026, 8, 16, tzinfo=timezone.utc),
            root=missing,
        )
        is None
    )
