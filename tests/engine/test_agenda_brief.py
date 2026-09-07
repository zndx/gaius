"""The Agenda Brief (2026-09-07): today · tomorrow · the coming week, written
before it is asked; `/agenda` = the brief + the index, `/agenda <id>` = one item.

Pinned behaviour:
- buckets are calendar days in the OPERATOR timezone (a late-UTC event lands
  on the next day in Auckland);
- `relevant` keeps everything today/tomorrow, only what matters in the week,
  only what is still open/pinned from before;
- the answer must carry BRIEF:/SPOKEN: (fail-fast) and SPOKEN is plain speech;
- the zettel chains prev/next to AGENDA BRIEF neighbours only and is never an
  Agenda item (list_items skips it);
- collect_agenda says honestly when there is no brief / no pool / no such item;
- the CLI default routes to the AgendaBrief RPC, an id routes to the item.
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from gaius.engine.services import agenda_brief as ab
from gaius.engine.services.agenda_notes import list_items

TZ = "Pacific/Auckland"
# 2026-09-07 09:00 UTC = 2026-09-07 21:00 in Auckland (NZST, +12)
NOW = datetime(2026, 9, 7, 9, 0, tzinfo=timezone.utc)
TODAY_NZ = date(2026, 9, 7)


def _note(root: Path, day: str, hhmmss: str, slug: str, *, kind: str, intent: str, title: str,
          starts: str = "", ends: str = "", pin: bool = False, body: str = "", with_whom: str = "") -> str:
    d = root / "scratch" / day
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{day}-{hhmmss}_{slug}.md"
    p.write_text(
        "[[current/agenda]]\n"
        f"kind: {kind}\nprev: \nnext: \nstarts: {starts}\nends: {ends}\ntags: t1, t2\n"
        f"pin: {'true' if pin else 'false'}\nintent: {intent}\nwith: {with_whom}\ntimezone: \n\n"
        f"# {title}\n\n{body or 'Body of ' + title}\n"
    )
    return str(p.relative_to(root))


@pytest.fixture
def kb(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    root = tmp_path / "kb"
    ids = {
        # today in Auckland (created 2026-09-07 local; undated note)
        "today_note": _note(root, "2026-09-07", "080000", "standup-notes", kind="note", intent="brief", title="Standup notes"),
        # 23:30 UTC on 09-07 = 11:30 on 09-08 in Auckland → TOMORROW there, today in UTC
        "late_session": _note(root, "2026-09-07", "090000", "review-with-ops", kind="event", intent="session",
                              title="Review with ops", starts="2026-09-07T23:30:00+00:00", ends="2026-09-08T00:00:00+00:00",
                              with_whom="ops"),
        # week: a session (kept) and an unpinned brief note (left out)
        "week_session": _note(root, "2026-09-10", "100000", "planning", kind="event", intent="session",
                              title="Quarter planning", starts="2026-09-10T02:00:00+00:00"),
        "week_noise": _note(root, "2026-09-11", "100000", "reading-list", kind="list", intent="brief", title="Reading list"),
        # past: a pinned reminder (kept) and a plain brief (left out)
        "past_pinned": _note(root, "2026-09-04", "100000", "renew-cert", kind="note", intent="reminder",
                             title="Renew the certificate", pin=True),
        "past_noise": _note(root, "2026-09-05", "100000", "yesterday-brief", kind="note", intent="brief", title="Yesterday brief"),
    }
    return root, ids


def test_bucket_for_edges():
    t = TODAY_NZ
    assert ab.bucket_for(t.isoformat(), t) == "today"
    assert ab.bucket_for((t + timedelta(days=1)).isoformat(), t) == "tomorrow"
    assert ab.bucket_for((t + timedelta(days=2)).isoformat(), t) == "week"
    assert ab.bucket_for((t + timedelta(days=7)).isoformat(), t) == "week"
    assert ab.bucket_for((t + timedelta(days=8)).isoformat(), t) == "later"
    assert ab.bucket_for((t - timedelta(days=1)).isoformat(), t) == "past"
    assert ab.bucket_for("", t) == "past"


def test_gather_buckets_in_operator_timezone_and_relevance(kb):
    root, ids = kb
    rows, today, total = ab.gather_items(root, zone=TZ, now=NOW)
    assert today == TODAY_NZ
    assert total == 6
    by_id = {r["id"]: r for r in rows}
    assert by_id[ids["today_note"]]["day"] == "today"
    # the 23:30 UTC session is TOMORROW in Auckland (and would be today in UTC)
    assert by_id[ids["late_session"]]["day"] == "tomorrow"
    assert by_id[ids["late_session"]]["calendar_day"] == "2026-09-08"
    assert by_id[ids["week_session"]]["day"] == "week"
    assert by_id[ids["past_pinned"]]["day"] == "past" and by_id[ids["past_pinned"]]["pinned"]
    assert ids["week_noise"] not in by_id, "an unpinned brief note in the week is not worth the brief"
    assert ids["past_noise"] not in by_id, "a plain past note is over"
    # order: today → tomorrow → week → past
    assert [r["day"] for r in rows] == ["today", "tomorrow", "week", "past"]
    # the same items in UTC: the late session is TODAY
    rows_utc, today_utc, _ = ab.gather_items(root, zone="UTC", now=NOW)
    assert today_utc == date(2026, 9, 7)
    assert {r["id"]: r["day"] for r in rows_utc}[ids["late_session"]] == "today"
    prompt = ab.build_prompt(rows, zone=TZ, today=today)
    assert "TODAY (2026-09-07)" in prompt and "TOMORROW (2026-09-08)" in prompt
    assert "Review with ops [session/event; with ops; Tue 2026-09-08 11:30–12:00]" in prompt
    assert "STILL OPEN FROM BEFORE TODAY:\n- Renew the certificate [reminder/note; pinned" in prompt


def test_parse_brief_is_strict_and_spoken_is_plain_speech():
    with pytest.raises(RuntimeError, match=ab.GURU_BRIEFFAIL):
        ab.parse_brief("BRIEF:\nonly a brief, no spoken section")
    with pytest.raises(RuntimeError, match=ab.GURU_BRIEFFAIL):
        ab.parse_brief("")
    brief, spoken = ab.parse_brief(
        "reasoning above the labels…\nBRIEF:\n**Today** is quiet.\n- one bullet\n\nSPOKEN:\n"
        "Today is **quiet**. See [x](http://e.x) later."
    )
    assert brief.startswith("**Today** is quiet.")
    assert "**" not in spoken and "http" not in spoken and "[" not in spoken
    assert spoken.startswith("Today is quiet.")


BRIEF_ANSWER = """Some reasoning the model left above the labels.

BRIEF:
Today is Standup notes and little else. Tomorrow, Review with ops at 11:30 matters.
This week, Quarter planning on Thursday. Renew the certificate is still open.

SPOKEN:
Today you have your standup notes and not much else. Tomorrow at half past eleven you review with ops. Later in the week there is quarter planning. The certificate renewal is still open.
"""


class _Conn:
    """asyncpg-shaped fake over agenda_briefs + cron.job."""

    def __init__(self, store: dict):
        self.store = store

    async def fetchrow(self, sql, *args):
        s = " ".join(sql.split())
        if s.startswith("INSERT INTO agenda_briefs"):
            row = {
                "id": uuid.uuid4(), "created_at": self.store["now"], "timezone": args[0], "today": args[1],
                "title": args[6], "body": args[7], "spoken": args[8], "items_considered": args[5],
                "item_ids": list(args[4]), "note_path": None, "model": args[9],
            }
            self.store["rows"].append(row)
            return {"id": row["id"], "created_at": row["created_at"]}
        if "FROM agenda_briefs ORDER BY created_at DESC LIMIT 1" in s:
            rows = sorted(self.store["rows"], key=lambda r: r["created_at"])
            return rows[-1] if rows else None
        if "WHERE created_at < $1" in s:
            older = sorted((r for r in self.store["rows"] if r["created_at"] < args[0]), key=lambda r: r["created_at"])
            return older[-1] if older else None
        raise AssertionError(f"unexpected fetchrow: {s[:80]}")

    async def fetchval(self, sql, *args):
        assert "cron.job" in sql
        return self.store.get("schedule")

    async def execute(self, sql, *args):
        assert sql.startswith("UPDATE agenda_briefs SET note_path")
        for r in self.store["rows"]:
            if str(r["id"]) == args[0]:
                r["note_path"] = args[1]


class _Acq:
    def __init__(self, c):
        self.c = c

    async def __aenter__(self):
        return self.c

    async def __aexit__(self, *a):
        return False


class _Pool:
    def __init__(self, store):
        self.c = _Conn(store)

    def acquire(self):
        return _Acq(self.c)


class _Client:
    def __init__(self, answer):
        self.answer = answer
        self.calls: list[dict] = []

    async def call(self, *, service, action, params):
        self.calls.append({"service": service, "action": action, "params": params})
        return {"success": True, "text": self.answer, "tokens_used": 321, "model": "thinking"}


def test_compose_persists_row_and_chains_agenda_brief_zettels_only(kb):
    root, ids = kb
    before = len(list_items(root, window_days=7, now=NOW, origin=TODAY_NZ.isoformat(), tz_name=TZ))
    store = {"rows": [], "now": NOW}
    pool, client = _Pool(store), _Client(BRIEF_ANSWER)

    first = asyncio.run(ab.compose_agenda_brief(pool, timezone_name=TZ, now=NOW, inference_client=client, kb_root=root))
    assert client.calls[0]["params"]["max_tokens"] == ab.REASONING_MAX_TOKENS
    assert client.calls[0]["params"]["agent"] == "thinking"
    assert first["items_considered"] == 4 and first["today"] == "2026-09-07"
    assert first["item_ids"] == [ids["today_note"], ids["late_session"], ids["week_session"], ids["past_pinned"]]
    assert first["spoken"].startswith("Today you have your standup notes")
    note1 = root / first["note_path"]
    assert note1.exists() and first["note_path"].startswith("scratch/2026-09-07/") and first["note_path"].endswith("_agenda_brief.md")
    text1 = note1.read_text()
    assert "prev: \n" in text1 and "type: agenda_brief" in text1 and f"timezone: {TZ}" in text1
    assert "## Spoken" in text1 and "## Covers" in text1
    for i in first["item_ids"]:
        assert f"[[{i}]]" in text1
    assert "kind:" not in text1.split("---")[0], "no kind header → never an Agenda item"

    # a second brief an hour later (still 2026-09-07 in Auckland): prev → the FIRST
    # BRIEF, and the first's next → the second
    store["now"] = NOW + timedelta(hours=1)
    second = asyncio.run(ab.compose_agenda_brief(pool, timezone_name=TZ, now=store["now"], inference_client=client, kb_root=root))
    note2 = root / second["note_path"]
    assert note2 != note1
    assert f"prev: [[{first['note_path']}]]" in note2.read_text()
    assert f"next: [[{second['note_path']}]]" in note1.read_text()
    # neither brief became an Agenda item
    after = list_items(root, window_days=7, now=NOW, origin=TODAY_NZ.isoformat(), tz_name=TZ)
    assert len(after) == before
    assert not any(p.path.endswith("_agenda_brief.md") for p in after)
    # the store row carries the note path and the index
    assert store["rows"][1]["note_path"] == second["note_path"]
    assert store["rows"][1]["item_ids"] == first["item_ids"]


def test_compose_fails_fast_on_a_bad_answer_or_no_pool(kb):
    root, _ = kb
    with pytest.raises(RuntimeError, match=ab.GURU_BRIEFFAIL):
        asyncio.run(ab.compose_agenda_brief(_Pool({"rows": [], "now": NOW}), timezone_name=TZ, now=NOW,
                                            inference_client=_Client("no labels here"), kb_root=root))
    with pytest.raises(RuntimeError, match=ab.GURU_BRIEFFAIL):
        asyncio.run(ab.compose_agenda_brief(None, timezone_name=TZ, now=NOW, inference_client=_Client(BRIEF_ANSWER), kb_root=root))


def test_collect_agenda_carries_brief_index_and_item_or_says_why_not(kb):
    root, ids = kb
    # no pool: the live index still comes back, with the NOPOOL note
    d = asyncio.run(ab.collect_agenda(None, now=NOW, kb_root=root, timezone_name=TZ))
    assert [r["id"] for r in d["items"]] == [ids["today_note"], ids["late_session"], ids["week_session"], ids["past_pinned"]]
    assert d["total_in_window"] == 6 and d["brief"] == "" and ab.GURU_NOPOOL in d["note"]
    assert "body" not in d["items"][0], "index rows carry no body"

    # pool, no brief yet: says when the next one is (from cron.job)
    store = {"rows": [], "now": NOW, "schedule": "13 1,5,9,13,17,21 * * *"}
    pool = _Pool(store)
    d = asyncio.run(ab.collect_agenda(pool, now=NOW, kb_root=root, timezone_name=TZ))
    assert "no agenda brief yet — next at 09:13 UTC" in d["note"]

    # a brief written yesterday (Auckland) → carried, with the honest date note; limit caps the index
    asyncio.run(ab.compose_agenda_brief(pool, timezone_name=TZ, now=NOW - timedelta(days=1), inference_client=_Client(BRIEF_ANSWER), kb_root=root))
    d = asyncio.run(ab.collect_agenda(pool, limit=2, now=NOW, kb_root=root, timezone_name=TZ))
    assert d["spoken"].startswith("Today you have your standup notes")
    assert d["brief_id"] == str(store["rows"][0]["id"]) and d["note_path"] == store["rows"][0]["note_path"]
    assert len(d["items"]) == 2 and d["total_in_window"] == 6
    assert "the brief was written for 2026-09-06; today is 2026-09-07" in d["note"]

    # one item in full, and a missing one said plainly
    d = asyncio.run(ab.collect_agenda(pool, note_id=ids["late_session"], now=NOW, kb_root=root, timezone_name=TZ))
    assert d["item"]["title"] == "Review with ops" and d["item"]["with_whom"] == "ops"
    assert d["item"]["body"].startswith("Body of Review with ops") and d["item"]["day"] == "tomorrow"
    d = asyncio.run(ab.collect_agenda(pool, note_id="scratch/2026-09-07/nope.md", now=NOW, kb_root=root, timezone_name=TZ))
    assert d["item"] is None and "item not found: scratch/2026-09-07/nope.md" in d["note"]

    # the proto carries the same
    hint = ab.to_proto(asyncio.run(ab.collect_agenda(pool, note_id=ids["today_note"], now=NOW, kb_root=root, timezone_name=TZ)))
    assert hint.project == "gaius" and hint.timezone == TZ and hint.today == "2026-09-07"
    assert hint.item.id == ids["today_note"] and hint.item.day == "today"
    assert [i.day for i in hint.items] == ["today", "tomorrow", "week", "past"]
    assert hint.spoken.startswith("Today you have")


def test_cli_agenda_default_is_the_brief_and_an_id_is_the_item():
    from gaius import cli as climod

    cls = next(c for c in vars(climod).values() if isinstance(c, type) and hasattr(c, "_cmd_agenda"))
    calls: list[tuple] = []

    class _Engine:
        async def call(self, service, action, params, timeout=None):
            calls.append((service, action, params))
            if params.get("item_id"):
                return {"item": {"id": params["item_id"], "title": "Review with ops", "kind": "event", "intent": "session",
                                 "starts": "2026-09-07T23:30:00+00:00", "day": "tomorrow", "body": "the body"}, "note": None}
            return {"brief": "B", "spoken": "S", "brief_at": "2026-09-07T05:13:00+00:00", "brief_age_s": 100,
                    "timezone": "UTC", "today": "2026-09-07", "items_considered": 1, "items": [
                        {"id": "scratch/2026-09-07/x.md", "day": "today", "kind": "note", "intent": "brief", "title": "X"}],
                    "total_in_window": 3, "note": None}

    cli = cls.__new__(cls)

    async def _client():
        return _Engine()

    cli._get_engine_client_cached = _client  # type: ignore[attr-defined]

    out = asyncio.run(cli._cmd_agenda(""))
    assert calls[-1] == ("Gaius", "AgendaBrief", {"item_id": "", "limit": 0})
    assert out["mode"] == "brief" and out["spoken"] == "S" and out["items"][0]["id"] == "scratch/2026-09-07/x.md"

    out = asyncio.run(cli._cmd_agenda("scratch/2026-09-07/2026-09-07-090000_review-with-ops.md"))
    assert calls[-1][1] == "AgendaBrief" and calls[-1][2]["item_id"].endswith("review-with-ops.md")
    assert out["mode"] == "item" and out["title"] == "Review with ops" and out["body"] == "the body"

    out = asyncio.run(cli._cmd_agenda("brief 3"))
    assert calls[-1][2] == {"item_id": "", "limit": 3}
