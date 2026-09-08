"""Agenda zettels: naming, prev/next, path jail."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from gaius.engine.services.agenda_notes import (
    AgendaError,
    create_item,
    find_standing_brief,
    get_item,
    google_calendar_url,
    item_calendar_day,
    jail_path,
    list_items,
    skewer,
    update_item,
    validate_intent,
    validate_kind,
    validate_timezone,
)


def test_skewer_and_kind() -> None:
    assert skewer("Set today's priorities!") == "set-todays-priorities"
    assert validate_kind("NOTE") == "note"
    with pytest.raises(AgendaError, match="AG.00000002"):
        validate_kind("reminder")


def test_jail_rejects_escape(tmp_path: Path) -> None:
    kb = tmp_path / "kb"
    kb.mkdir()
    (kb / "scratch").mkdir()
    with pytest.raises(AgendaError, match="AG.00000003"):
        jail_path(kb, "../secret.md")
    with pytest.raises(AgendaError, match="AG.00000003"):
        jail_path(kb, "current/projects/x.md")


def test_create_list_get_update_chain(tmp_path: Path) -> None:
    kb = tmp_path / "build" / "dev"
    (kb / "scratch").mkdir(parents=True)
    t0 = datetime(2026, 8, 16, 18, 14, 30, tzinfo=timezone.utc)
    a = create_item(kb, kind="note", title="First thought", body="hello", now=t0)
    assert a.path == "scratch/2026-08-16/2026-08-16-181430_first-thought.md"
    assert a.prev == ""
    t1 = datetime(2026, 8, 16, 18, 15, 1, tzinfo=timezone.utc)
    b = create_item(kb, kind="note", title="Second", body="there", now=t1)
    assert b.prev == a.path
    again = get_item(kb, a.path)
    assert again.next == b.path
    listed = list_items(kb, window_days=14, now=t1)
    assert [i.path for i in listed] == [b.path, a.path]
    updated = update_item(kb, b.path, body="there!\n", pin=True)
    assert updated.pin is True
    assert "there!" in updated.body


def test_list_kind_filter_and_missing(tmp_path: Path) -> None:
    kb = tmp_path / "kb"
    kb.mkdir()
    (kb / "scratch").mkdir()
    now = datetime(2026, 8, 16, 12, 0, 0, tzinfo=timezone.utc)
    create_item(kb, kind="list", title="Shop", now=now)
    create_item(
        kb,
        kind="event",
        title="Call",
        starts="2026-08-16T17:00:00+00:00",
        now=now,
    )
    notes = list_items(kb, kind="list", now=now)
    assert len(notes) == 1
    assert notes[0].checks
    with pytest.raises(AgendaError, match="AG.00000003"):
        get_item(kb, "scratch/2026-08-16/nope.md")


def test_session_requires_starts(tmp_path: Path) -> None:
    kb = tmp_path / "kb"
    (kb / "scratch").mkdir(parents=True)
    with pytest.raises(AgendaError, match="AG.00000006"):
        create_item(kb, kind="event", title="Talk", intent="session")
    with pytest.raises(AgendaError, match="AG.00000007"):
        validate_intent("attention", "note")
    item = create_item(
        kb,
        kind="event",
        title="Talk",
        intent="session",
        starts="2026-08-14T13:00:00+00:00",
    )
    assert item.intent == "session"
    assert item.with_whom == "agents"
    assert item.ends
    url = item.calendar_url()
    assert url.startswith("https://calendar.google.com/calendar/render?")
    assert "action=TEMPLATE" in url
    assert google_calendar_url(title="x", starts="") == ""


def test_calendar_details_omit_cta(tmp_path: Path) -> None:
    kb = tmp_path / "kb"
    (kb / "scratch").mkdir(parents=True)
    item = create_item(
        kb,
        kind="event",
        title="Talk",
        intent="session",
        starts="2026-08-14T13:00:00+00:00",
        body=(
            "Walk the watchlist.\n\n"
            "[Add to Google Calendar](https://calendar.google.com/calendar/render?action=TEMPLATE&text=Talk)\n"
        ),
    )
    url = item.calendar_url()
    assert "Add+to+Google+Calendar" not in url
    assert "Add%20to%20Google%20Calendar" not in url
    assert "calendar.google.com" in url
    from urllib.parse import parse_qs, urlparse

    details = parse_qs(urlparse(url).query).get("details", [""])[0]
    assert "Add to Google Calendar" not in details
    assert "Walk the watchlist" in details
    assert "Add to Google Calendar" not in item.excerpt()


def test_calendar_omits_presenterm_deck_and_puts_join_in_location(tmp_path: Path) -> None:
    kb = tmp_path / "kb"
    (kb / "scratch").mkdir(parents=True)
    item = create_item(
        kb,
        kind="event",
        title="Watchlist after the tape",
        intent="session",
        starts="2026-09-08T20:00:00+00:00",
        body=(
            "A half hour to decide whether the book moves.\n\n"
            "## Deck\n\n"
            "Opening\n===\n\n"
            "Would you change the book today?\n\n"
            "<!-- speaker_note: Intel raise, Lilly growth, Disney beat. -->\n"
            "<!-- end_slide -->\n"
        ),
    )
    join = item.join_url()
    from urllib.parse import parse_qs, unquote, urlparse

    ju = urlparse(join)
    assert ju.scheme == "https"
    assert ju.hostname == "tinybox.dev.vista.zndx.org"
    assert ju.port == 9120
    assert ju.path == "/listen"
    assert "watchlist-after-the-tape" in ju.query
    url = item.calendar_url()

    q = parse_qs(urlparse(url).query)
    details = q.get("details", [""])[0]
    location = q.get("location", [""])[0]
    assert "Join AgentRTC" in details
    assert "tinybox.dev.vista.zndx.org:9120/listen" in details
    assert "speaker_note" not in details
    assert "end_slide" not in details
    assert "Would you change the book" not in details
    loc = urlparse(unquote(location))
    assert loc.hostname == "tinybox.dev.vista.zndx.org"
    assert loc.port == 9120


def test_calendar_strips_operator_paste_and_forces_listen_port(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HERMES_AGENT_RTC_JOIN_URL", "https://tinybox.dev.vista.zndx.org/listen")
    kb = tmp_path / "kb"
    (kb / "scratch").mkdir(parents=True)
    item = create_item(
        kb,
        kind="event",
        title="Discover coherence check-in",
        intent="session",
        starts="2026-09-07T16:00:00+00:00",
        body=(
            "Half an hour to decide whether you would send a colleague to Discover.\n\n"
            "---\n"
            "Operator paste (not for the voice):\n\n"
            "BEGIN SESSION\nepisode=abc\nDiscover coherence check-in\nEND SESSION\n"
        ),
    )
    from urllib.parse import parse_qs, unquote, urlparse

    q = parse_qs(urlparse(item.calendar_url()).query)
    details = q.get("details", [""])[0]
    location = unquote(q.get("location", [""])[0])
    assert "BEGIN SESSION" not in details
    assert "episode=" not in details
    assert "Operator paste" not in details
    assert "send a colleague" in details
    assert urlparse(location).port == 9120
    assert urlparse(item.join_url()).port == 9120


def test_origin_timezone_window_and_local_day(tmp_path: Path) -> None:
    kb = tmp_path / "kb"
    (kb / "scratch").mkdir(parents=True)
    item = create_item(
        kb,
        kind="event",
        title="Nine PM MDT",
        starts="2026-08-17T03:00:00+00:00",
        tz_name="America/Denver",
        now=datetime(2026, 8, 16, 21, 0, 0, tzinfo=timezone.utc),
    )
    assert item.timezone == "America/Denver"
    assert item_calendar_day(item, tz_name="America/Denver") == "2026-08-16"
    assert item_calendar_day(item, tz_name="") == "2026-08-17"
    hits = list_items(
        kb,
        window_days=1,
        origin="2026-08-16",
        tz_name="America/Denver",
        now=datetime(2026, 8, 17, 4, 0, 0, tzinfo=timezone.utc),
    )
    assert [i.title for i in hits] == ["Nine PM MDT"]
    with pytest.raises(AgendaError, match="AG.00000009"):
        list_items(kb, origin="17 August")
    with pytest.raises(AgendaError, match="AG.00000010"):
        validate_timezone("MDT")


def test_list_window_uses_starts_not_created(tmp_path: Path) -> None:
    kb = tmp_path / "kb"
    (kb / "scratch").mkdir(parents=True)
    now = datetime(2026, 8, 16, 12, 0, 0, tzinfo=timezone.utc)
    create_item(
        kb,
        kind="event",
        title="Far session",
        intent="session",
        starts="2026-11-14T13:00:00+00:00",
        now=datetime(2026, 11, 14, 13, 0, 0, tzinfo=timezone.utc),
    )
    create_item(
        kb,
        kind="note",
        title="Today brief",
        now=now,
    )
    near = list_items(kb, window_days=14, now=now)
    assert [i.title for i in near] == ["Today brief"]
    wide = list_items(kb, window_days=120, now=now)
    titles = {i.title for i in wide}
    assert "Far session" in titles
    assert "Today brief" in titles


def test_list_skips_legacy_scratch_without_kind(tmp_path: Path) -> None:
    kb = tmp_path / "kb"
    day = kb / "scratch" / "2026-08-16"
    day.mkdir(parents=True)
    (day / "015838_prospects_sitrep.md").write_text(
        "---\ntitle: sitrep\n---\n# Sitrep\n\nnoise\n",
        encoding="utf-8",
    )
    now = datetime(2026, 8, 16, 18, 0, 0, tzinfo=timezone.utc)
    create_item(kb, kind="note", title="Real card", now=now)
    listed = list_items(kb, now=now)
    assert [i.title for i in listed] == ["Real card"]
    assert listed[0].prev == ""


def test_find_standing_brief_prefers_latest_w34(tmp_path: Path) -> None:
    kb = tmp_path / "kb"
    old = kb / "scratch" / "2026-08-17"
    new = kb / "scratch" / "2026-08-24"
    old.mkdir(parents=True)
    new.mkdir(parents=True)
    (old / "2026-08-17-024851_w34-summary.md").write_text(
        "kind: note\nintent: brief\n\n# Old W34\n\nchangelog\n",
        encoding="utf-8",
    )
    (new / "2026-08-24-150000_w34-summary.md").write_text(
        "kind: note\nintent: brief\n\n# Weekly Signals Summary · 2026-W34\n\ncommits\n",
        encoding="utf-8",
    )
    hit = find_standing_brief(kb)
    assert hit is not None
    assert hit.path.endswith("2026-08-24-150000_w34-summary.md")
    assert "Weekly Signals Summary" in hit.title
