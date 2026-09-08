"""The Agenda Brief — today, tomorrow and the coming week, written before it is asked.

User (2026-09-07): "`/agenda` to return a pre-prepared brief-formatted summary
of today's Agenda items along with tomorrow and the coming week. This
obviously requires our local thinking capability to understand the gist of
today's agenda, and make some judgement calls about what to include from
tomorrow and the week ahead … the voice agent only needs to call `/agenda` …
return the content from specific agenda items … passing the item ID as an
argument."

Same paradigm as the Thoughts Brief (`thoughts_brief.py`): ONE thinking Complete
over the Agenda items of a 7-day window (the same items `AgendaList` serves),
pre-structured by calendar bucket in the operator's timezone — TODAY, TOMORROW,
the WEEK, and past-but-open reminders — in the Agenda framing, first person as
the operator's agenda-keeper. Two outputs: the written BRIEF and the plain-
speech SPOKEN form. Persisted to `agenda_briefs` AND as a zettel under the
day's scratch tree whose prev/next link ONLY the neighbouring agenda briefs.
The items it covered are the INDEX (id = note path) a conversational agent
follows up with: `/agenda <id>`.

Never an Agenda item itself: the zettel carries no `kind:` header and its
filename is not in the Agenda's NEW_NAME shape, so `list_items` skips it.

Fail-fast: a missing section, an empty answer or a store error raises
#AG.00000001.BRIEFFAIL with the evidence; nothing partial is written.
"""
from __future__ import annotations

import json
import logging
import os
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from gaius.core.budgets import REASONING_MAX_TOKENS

logger = logging.getLogger(__name__)

GURU_BRIEFFAIL = "#AG.00000001.BRIEFFAIL"
GURU_NOPOOL = "#AG.00000002.NOPOOL"
GURU_STOREFAIL = "#AG.00000003.STOREFAIL"

NOTE_TYPE = "agenda_brief"            # zettel filename suffix: <HHMMSS>_agenda_brief.md
WINDOW_DAYS = 7                       # today + 7 ahead; 7 back for open reminders
INDEX_MAX = 24
BRIEF_MAX_CHARS = 1400
SPOKEN_MAX_CHARS = 800
SUMMARY_CHARS = 300
BODY_CHARS = 4000
EXCERPT_CHARS = 240
DEFAULT_TIMEZONE = "UTC"
CRON_JOB = "agenda-brief"
_MARKDOWN_RE = re.compile(r"(^\s*[-*•]\s|^\s*#{1,6}\s|\*\*|`|\[[^\]]+\]\([^)]+\)|https?://)", re.M)

BUCKETS = ("today", "tomorrow", "week", "past", "later")

SYSTEM_PROMPT = (
    "You are the operator's agenda-keeper writing the Agenda Brief in the first "
    "person: the gist of TODAY, what from TOMORROW matters, and what in the coming "
    "WEEK deserves attention. Summarise and judge what is on the agenda — do not "
    "invent items, refer to items by their titles, and say plainly when a day is empty."
)


# ── configuration ────────────────────────────────────────────────────────────
def operator_timezone() -> str:
    """IANA zone the brief speaks in: GAIUS_AGENDA_TZ, else the supervision
    instance's `timezone` attr, else UTC. Documented default: UTC."""
    env = (os.environ.get("GAIUS_AGENDA_TZ") or "").strip()
    if env:
        try:
            ZoneInfo(env)
            return env
        except Exception:  # noqa: BLE001 — a bad env zone is said, not guessed silently
            logger.warning("GAIUS_AGENDA_TZ=%r is not an IANA zone; using %s", env, DEFAULT_TIMEZONE)
    try:
        from gaius.engine.supervision_spec import load_spec

        spec = load_spec()
        attrs = getattr(getattr(spec, "supervisor", None), "attrs", None) or []
        for a in attrs:
            if getattr(a, "key", "") == "timezone" and getattr(a, "value", ""):
                ZoneInfo(a.value)
                return a.value
    except Exception:  # noqa: BLE001 — the instance is optional here
        pass
    return DEFAULT_TIMEZONE


# ── gather + bucket ──────────────────────────────────────────────────────────
def _clip(text: str | None, n: int) -> str:
    s = re.sub(r"\s+", " ", (text or "")).strip()
    if len(s) <= n:
        return s
    return s[: n - 1].rsplit(" ", 1)[0] + "…"


def _item_day(item: Any, zone: str) -> str:
    """Calendar day (YYYY-MM-DD in `zone`) an item belongs to: its start for
    dated items, else the day it was created."""
    from gaius.engine.services.agenda_notes import item_calendar_day

    day = item_calendar_day(item, tz_name=zone) if zone else item_calendar_day(item)
    if day:
        return day
    if item.created_ms:
        return datetime.fromtimestamp(item.created_ms / 1000, tz=timezone.utc).astimezone(ZoneInfo(zone)).date().isoformat()
    return ""


def bucket_for(day: str, today: date) -> str:
    """today | tomorrow | week (2..7 days ahead) | past | later."""
    if not day:
        return "past"
    d = date.fromisoformat(day)
    delta = (d - today).days
    if delta == 0:
        return "today"
    if delta == 1:
        return "tomorrow"
    if 2 <= delta <= WINDOW_DAYS:
        return "week"
    if delta < 0:
        return "past"
    return "later"


def _open_checks(item: Any) -> int:
    return sum(1 for c in (item.checks or []) if not c.get("done"))


def item_row(item: Any, *, zone: str, today: date, with_body: bool = False) -> dict[str, Any]:
    """The index shape (AgendaHintItem): id = note path; body only on request."""
    from gaius.engine.services.agenda_notes import parse_when, split_public_deck

    def _ms(iso: str) -> int:
        dt = parse_when(iso) if iso else None
        return int(dt.timestamp() * 1000) if dt else 0

    day = _item_day(item, zone)
    row = {
        "id": item.path,
        "starts_ms": _ms(item.starts),
        "ends_ms": _ms(item.ends),
        "kind": item.kind,
        "intent": item.intent,
        "title": item.title,
        "summary": _clip(split_public_deck(item.body)[0], SUMMARY_CHARS),
        "tags": list(item.tags or []),
        "pinned": bool(item.pin),
        "open_checks": _open_checks(item),
        "with_whom": item.with_whom or "",
        "created_ms": int(item.created_ms or 0),
        "day": bucket_for(day, today),
        "calendar_day": day,
    }
    if with_body:
        # Sessions keep the presenterm deck intact (off-invite guide).
        if item.intent == "session":
            row["body"] = (item.body or "").strip()
        else:
            row["body"] = _clip_body(item.body)
    return row


def _clip_body(body: str) -> str:
    text = (body or "").strip()
    if len(text) <= BODY_CHARS:
        return text
    return text[: BODY_CHARS - 1].rsplit("\n", 1)[0] + "\n…"


def relevant(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """What the brief covers: everything today and tomorrow; sessions, pinned
    items and reminders with open checks in the week; past reminders still
    open or pinned (the lookback). Ordered today → tomorrow → week → past,
    sessions by start, then pinned, then newest."""
    keep: list[dict[str, Any]] = []
    for r in rows:
        b = r["day"]
        if b in ("today", "tomorrow"):
            keep.append(r)
        elif b == "week" and (r["intent"] == "session" or r["pinned"] or r["open_checks"] > 0):
            keep.append(r)
        elif b == "past" and (r["pinned"] or (r["intent"] == "reminder" and r["open_checks"] > 0)):
            keep.append(r)
    order = {"today": 0, "tomorrow": 1, "week": 2, "past": 3, "later": 4}
    keep.sort(
        key=lambda r: (
            order.get(r["day"], 9),
            0 if r["intent"] == "session" else 1,
            r["starts_ms"] or 10**18,
            not r["pinned"],
            -int(r["created_ms"] or 0),
        )
    )
    return keep[:INDEX_MAX]


def gather_items(kb_root: Path, *, zone: str, now: datetime) -> tuple[list[dict[str, Any]], date, int]:
    """(index rows the brief covers, today, total items in the window) — the
    same items AgendaList serves, bucketed in the operator's timezone."""
    from gaius.engine.services.agenda_notes import list_items

    today = now.astimezone(ZoneInfo(zone)).date()
    items = list_items(kb_root, window_days=WINDOW_DAYS, now=now, origin=today.isoformat(), tz_name=zone)
    rows = [item_row(i, zone=zone, today=today) for i in items]
    return relevant(rows), today, len(items)


# ── prompt / parse ───────────────────────────────────────────────────────────
def _when(r: dict[str, Any], zone: str) -> str:
    if r["starts_ms"]:
        dt = datetime.fromtimestamp(r["starts_ms"] / 1000, tz=timezone.utc).astimezone(ZoneInfo(zone))
        end = ""
        if r["ends_ms"]:
            end = "–" + datetime.fromtimestamp(r["ends_ms"] / 1000, tz=timezone.utc).astimezone(ZoneInfo(zone)).strftime("%H:%M")
        return dt.strftime("%a %Y-%m-%d %H:%M") + end
    return r.get("calendar_day") or ""


def build_prompt(rows: list[dict[str, Any]], *, zone: str, today: date) -> str:
    groups: dict[str, list[str]] = {b: [] for b in BUCKETS}
    for r in rows:
        flags = []
        if r["pinned"]:
            flags.append("pinned")
        if r["open_checks"]:
            flags.append(f"{r['open_checks']} open item(s)")
        if r["with_whom"]:
            flags.append(f"with {r['with_whom']}")
        meta = f"{r['intent']}/{r['kind']}" + (f"; {', '.join(flags)}" if flags else "")
        when = _when(r, zone)
        line = f"- {r['title']} [{meta}{'; ' + when if when else ''}]"
        if r["summary"]:
            line += f"\n    {_clip(r['summary'], EXCERPT_CHARS)}"
        groups[r["day"]].append(line)
    sections = []
    labels = {
        "today": f"TODAY ({today.isoformat()})",
        "tomorrow": f"TOMORROW ({(today + timedelta(days=1)).isoformat()})",
        "week": f"THE COMING WEEK ({(today + timedelta(days=2)).isoformat()} … {(today + timedelta(days=WINDOW_DAYS)).isoformat()})",
        "past": "STILL OPEN FROM BEFORE TODAY",
        "later": "LATER",
    }
    for b in BUCKETS:
        if b == "later" and not groups[b]:
            continue
        body = "\n".join(groups[b]) if groups[b] else "  (nothing on the agenda)"
        sections.append(f"{labels[b]}:\n{body}")
    evidence = "\n\n".join(sections)
    return f"""My Agenda, in the {zone} timezone. Today is {today.strftime('%A %Y-%m-%d')}.

{evidence}

Write my Agenda Brief in exactly two sections, each starting on its own line with the label:

BRIEF:
The written brief, at most {BRIEF_MAX_CHARS} characters. First person. Give the gist of today; say what from tomorrow matters and why; pick what in the coming week deserves attention and leave out what does not; mention still-open reminders only if they matter. Refer to items by their titles. If a day is empty, say so in one clause. Choose your own structure; stay within the length.

SPOKEN:
The same brief for a voice agent to say aloud: plain speech, five to eight sentences, at most {SPOKEN_MAX_CHARS} characters. No markdown, no lists, no links, no code, no headings — words only.

Do not add anything after the SPOKEN section."""


def parse_brief(text: str) -> tuple[str, str]:
    """Extract (brief, spoken); both required, spoken must be plain speech."""
    raw = (text or "").strip()
    m = re.search(r"BRIEF:\s*(.*?)\n\s*SPOKEN:\s*(.*)\Z", raw, re.S | re.I)
    if not m:
        raise RuntimeError(
            f"{GURU_BRIEFFAIL} the agenda brief answer lacks BRIEF:/SPOKEN: sections "
            f"(chars={len(raw)}); tail: {raw[-300:]!r}\n"
            "  Try: the next agenda_brief tick rewrites it (cron agenda-brief)"
        )
    brief = m.group(1).strip()
    spoken = m.group(2).strip()
    if not brief or not spoken:
        raise RuntimeError(f"{GURU_BRIEFFAIL} empty BRIEF or SPOKEN section; tail: {raw[-300:]!r}")
    if _MARKDOWN_RE.search(spoken):
        spoken = re.sub(r"\s+", " ", _MARKDOWN_RE.sub("", spoken)).strip()
    if len(brief) > BRIEF_MAX_CHARS * 2 or len(spoken) > SPOKEN_MAX_CHARS * 2:
        raise RuntimeError(
            f"{GURU_BRIEFFAIL} brief far over length (brief={len(brief)}, spoken={len(spoken)} chars)"
        )
    return brief, spoken


def _title_from(brief: str, today: date) -> str:
    first = brief.split("\n", 1)[0].strip().lstrip("#* ")
    m = re.match(r"(.{10,80}?[.!?])(\s|$)", first)
    title = m.group(1) if m else first
    if len(title) > 80:
        title = title[:80].rsplit(" ", 1)[0].rstrip("—–- ,.:;")
    return title.strip() or f"Agenda Brief {today.isoformat()}"


# ── zettel ───────────────────────────────────────────────────────────────────
def save_brief_as_zettel(
    *,
    brief: str,
    spoken: str,
    rows: list[dict[str, Any]],
    brief_id: str,
    zone: str,
    today: date,
    now: datetime,
    kb_root: Path,
) -> str:
    """Write the Brief as a KB note under scratch/<date>/, prev/next-linked to
    the previous AGENDA BRIEF note only (the brief chain). No `kind:` header and
    an OLD_NAME-shaped filename → never an Agenda item. Returns the note path
    relative to the KB root."""
    from gaius.core.project_notes import _update_next_link, find_previous_project_note

    root = kb_root
    prev_note = find_previous_project_note(root, NOTE_TYPE)
    local = now.astimezone(ZoneInfo(zone))
    scratch_dir = root / "scratch" / local.strftime("%Y-%m-%d")
    scratch_dir.mkdir(parents=True, exist_ok=True)
    prev_link = ""
    if prev_note:
        try:
            prev_link = f"[[{prev_note.relative_to(root)}]]"
        except ValueError:
            prev_link = f"[[{prev_note.stem}]]"
    lines = [
        "[[current/agents/theta]]",
        f"prev: {prev_link}",
        "next:",
        "",
        f"# Agenda Brief - {local.strftime('%Y-%m-%d %H:%M')} {zone}",
        "",
        "---",
        f"type: {NOTE_TYPE}",
        f"created: {now.isoformat()}",
        f"brief_id: {brief_id}",
        f"timezone: {zone}",
        f"today: {today.isoformat()}",
        f"items_covered: {len(rows)}",
        "---",
        "",
        brief,
        "",
        "## Spoken",
        "",
        spoken,
        "",
        "## Covers",
        "",
    ]
    for r in rows:
        when = _when(r, zone)
        lines.append(f"- {r['day']} · {r['intent']} · {r['title']}{' · ' + when if when else ''} — [[{r['id']}]]")
    lines += ["", "---", "", "*Written by the agenda_brief task. Edit, link, or dismiss as you wish.*", ""]
    note_path = scratch_dir / f"{local.strftime('%H%M%S')}_{NOTE_TYPE}.md"
    note_path.write_text("\n".join(lines))
    if prev_note and prev_note.exists():
        _update_next_link(prev_note, root, note_path)
    rel = str(note_path.relative_to(root))
    logger.info("agenda brief zettel written: %s (prev %s)", rel, prev_link or "-")
    return rel


# ── compose ──────────────────────────────────────────────────────────────────
async def _complete(inference_client, prompt: str) -> tuple[str, int, str]:
    from gaius.engine.services.cognition_logic import _validate_complete_response

    response = await inference_client.call(
        service="Scheduler",
        action="complete",
        params={
            "prompt": prompt,
            "system_prompt": SYSTEM_PROMPT,
            "agent": "thinking",
            "max_tokens": REASONING_MAX_TOKENS,
        },
    )
    text, tokens = _validate_complete_response(response, context="agenda_brief")
    model = ""
    if isinstance(response, dict):
        model = str(response.get("model") or response.get("model_name") or "")
    return text, int(tokens or 0), model


async def compose_agenda_brief(
    db_pool,
    *,
    timezone_name: str | None = None,
    now: datetime | None = None,
    inference_client=None,
    kb_root: Path | None = None,
) -> dict[str, Any]:
    """Gather the week's Agenda items, write the Brief (one thinking Complete),
    persist to agenda_briefs and as a prev/next-linked zettel. Fail-fast."""
    from gaius.engine.services.agenda_notes import kb_root_from_env

    now = now or datetime.now(timezone.utc)
    zone = timezone_name or operator_timezone()
    if db_pool is None:
        raise RuntimeError(f"{GURU_BRIEFFAIL} no database pool — cannot persist an agenda brief")
    root = kb_root or kb_root_from_env()
    rows, today, total = gather_items(root, zone=zone, now=now)
    if inference_client is None:
        from gaius.client import get_grpc_client

        inference_client = await get_grpc_client()
        if inference_client is None:
            raise RuntimeError(f"{GURU_BRIEFFAIL} engine gRPC client unavailable — the brief needs thinking")

    prompt = build_prompt(rows, zone=zone, today=today)
    text, tokens, model = await _complete(inference_client, prompt)
    if not (text or "").strip():
        raise RuntimeError(f"{GURU_BRIEFFAIL} thinking answered nothing (tokens={tokens}); the trace is not a brief")
    brief, spoken = parse_brief(text)
    title = _title_from(brief, today)
    item_ids = [r["id"] for r in rows]
    days = [r["calendar_day"] for r in rows if r.get("calendar_day")]
    context = {
        "max_tokens": REASONING_MAX_TOKENS,
        "response_chars": len(text),
        "prompt_chars": len(prompt),
        "window_days": WINDOW_DAYS,
        "items_in_window": total,
        "buckets": {b: sum(1 for r in rows if r["day"] == b) for b in BUCKETS},
    }
    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO agenda_briefs
                    (timezone, today, window_start, window_end, item_ids, items_considered,
                     title, body, spoken, model, tokens_used, generation_context)
                VALUES ($1, $2, $3, $4, $5::text[], $6, $7, $8, $9, $10, $11, $12::jsonb)
                RETURNING id, created_at
                """,
                zone,
                today,
                date.fromisoformat(min(days)) if days else today,
                date.fromisoformat(max(days)) if days else today,
                item_ids,
                len(rows),
                title,
                brief,
                spoken,
                model or None,
                tokens,
                json.dumps(context),
            )
    except Exception as e:  # noqa: BLE001 — surfaced with the guru, never a half-written brief
        raise RuntimeError(f"{GURU_BRIEFFAIL} persisting the agenda brief failed: {e}\n  Try: /health fix postgres") from e
    brief_id = str(row["id"])
    created_at = row["created_at"]
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    note_path = save_brief_as_zettel(
        brief=brief, spoken=spoken, rows=rows, brief_id=brief_id, zone=zone, today=today,
        now=created_at, kb_root=root,
    )
    async with db_pool.acquire() as conn:
        await conn.execute("UPDATE agenda_briefs SET note_path = $2 WHERE id = $1::uuid", brief_id, note_path)
    logger.info(
        "agenda brief %s written: %d items covered of %d in window, %d chars written / %d spoken, note %s",
        brief_id, len(rows), total, len(brief), len(spoken), note_path,
    )
    return {
        "id": brief_id,
        "created_at": created_at,
        "title": title,
        "body": brief,
        "spoken": spoken,
        "timezone": zone,
        "today": today.isoformat(),
        "items_considered": len(rows),
        "item_ids": item_ids,
        "items": rows,
        "model": model,
        "tokens": tokens,
        "note_path": note_path,
    }


# ── read ─────────────────────────────────────────────────────────────────────
async def latest_brief(db_pool) -> dict[str, Any] | None:
    if db_pool is None:
        return None
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, created_at, timezone, today, title, body, spoken, items_considered, item_ids, note_path, model
            FROM agenda_briefs ORDER BY created_at DESC LIMIT 1
            """
        )
        if row is None:
            return None
        prev = await conn.fetchrow(
            "SELECT id, note_path FROM agenda_briefs WHERE created_at < $1 ORDER BY created_at DESC LIMIT 1",
            row["created_at"],
        )
    at = row["created_at"]
    if at.tzinfo is None:
        at = at.replace(tzinfo=timezone.utc)
    return {
        "id": str(row["id"]),
        "created_at": at,
        "at_ms": int(at.timestamp() * 1000),
        "timezone": row["timezone"] or DEFAULT_TIMEZONE,
        "today": row["today"].isoformat() if row["today"] else "",
        "title": row["title"] or "",
        "body": row["body"] or "",
        "spoken": row["spoken"] or "",
        "items_considered": int(row["items_considered"] or 0),
        "item_ids": list(row["item_ids"] or []),
        "note_path": row["note_path"] or "",
        "model": row["model"] or "",
        "prev_brief_id": str(prev["id"]) if prev else "",
        "prev_note_path": (prev["note_path"] or "") if prev else "",
        "next_note_path": "",
    }


async def next_brief_at(db_pool, now: datetime) -> datetime | None:
    """When the agenda-brief enqueuer next fires, from cron.job."""
    from gaius.engine.services.thoughts_brief import next_cron_fire

    if db_pool is None:
        return None
    try:
        async with db_pool.acquire() as conn:
            sched = await conn.fetchval(
                "SELECT schedule FROM cron.job WHERE jobname = $1 AND active", CRON_JOB
            )
    except Exception:  # noqa: BLE001 — cron.job may be unreadable; the note just says less
        return None
    return next_cron_fire(str(sched or ""), now) if sched else None


async def collect_agenda(
    db_pool,
    *,
    note_id: str = "",
    limit: int = 0,
    now: datetime | None = None,
    kb_root: Path | None = None,
    timezone_name: str | None = None,
) -> dict[str, Any]:
    """Plain-dict form of the AgendaHint: the latest brief, the LIVE index of
    covered items (re-read from the KB so titles/checks are current), and the
    one item asked for by `note_id` (with body). No model call. Honest notes."""
    from gaius.engine.services.agenda_notes import AgendaError, get_item, kb_root_from_env

    now = now or datetime.now(timezone.utc)
    zone = timezone_name or operator_timezone()
    out: dict[str, Any] = {
        "project": "gaius",
        "brief": "",
        "spoken": "",
        "brief_at_ms": 0,
        "brief_id": "",
        "timezone": zone,
        "today": now.astimezone(ZoneInfo(zone)).date().isoformat(),
        "items": [],
        "item": None,
        "total_in_window": 0,
        "note": "",
        "note_path": "",
        "prev_note_path": "",
        "next_note_path": "",
        "prev_brief_id": "",
        "items_considered": 0,
    }
    notes: list[str] = []
    root = kb_root or kb_root_from_env()
    try:
        rows, today, total = gather_items(root, zone=zone, now=now)
    except Exception as e:  # noqa: BLE001 — the KB may be absent on a bare host; say so
        rows, today, total = [], now.astimezone(ZoneInfo(zone)).date(), 0
        notes.append(f"{GURU_STOREFAIL} agenda items unreadable: {e}")
    n = int(limit or 0)
    out["items"] = rows[:n] if n > 0 else rows
    out["total_in_window"] = total
    out["today"] = today.isoformat()
    if not rows and not notes:
        notes.append("agenda empty for today, tomorrow and the coming week")

    if db_pool is None:
        notes.append(f"{GURU_NOPOOL} agenda brief store unavailable (engine still booting?)\n  Try: /health")
    else:
        try:
            b = await latest_brief(db_pool)
            if b is not None:
                out.update(
                    {
                        "brief": b["body"],
                        "spoken": b["spoken"],
                        "brief_at_ms": b["at_ms"],
                        "brief_id": b["id"],
                        "timezone": b["timezone"] or zone,
                        "note_path": b["note_path"],
                        "prev_note_path": b["prev_note_path"],
                        "next_note_path": b["next_note_path"],
                        "prev_brief_id": b["prev_brief_id"],
                        "items_considered": b["items_considered"],
                    }
                )
                if b["today"] and b["today"] != today.isoformat():
                    notes.append(f"the brief was written for {b['today']}; today is {today.isoformat()}")
            else:
                nxt = await next_brief_at(db_pool, now)
                when = nxt.strftime("%H:%M UTC") if nxt else "the next agenda_brief tick"
                notes.append(f"no agenda brief yet — next at {when}")
        except Exception as e:  # noqa: BLE001 — a store problem is said, not hidden
            logger.warning("%s agenda brief read failed: %s", GURU_STOREFAIL, e)
            notes.append(f"{GURU_STOREFAIL} agenda brief unavailable: {e}")

    wanted = (note_id or "").strip()
    if wanted:
        try:
            item = get_item(root, wanted)
            out["item"] = item_row(item, zone=zone, today=today, with_body=True)
        except (AgendaError, FileNotFoundError, OSError, ValueError) as e:
            notes.append(f"item not found: {wanted} ({str(e).splitlines()[0][:120]})")
    out["note"] = "; ".join(notes)
    return out


def to_proto(d: dict[str, Any]):
    """Dict → zndx.engine.v1.AgendaHint."""
    from gaius.engine.generated.zndx.engine.v1 import engine_pb2 as zpb

    def _item(r: dict[str, Any]):
        it = zpb.AgendaHintItem(
            id=str(r.get("id") or ""),
            starts_ms=int(r.get("starts_ms") or 0),
            ends_ms=int(r.get("ends_ms") or 0),
            kind=str(r.get("kind") or ""),
            intent=str(r.get("intent") or ""),
            title=str(r.get("title") or ""),
            summary=str(r.get("summary") or ""),
            pinned=bool(r.get("pinned")),
            open_checks=int(r.get("open_checks") or 0),
            with_whom=str(r.get("with_whom") or ""),
            body=str(r.get("body") or ""),
            created_ms=int(r.get("created_ms") or 0),
            day=str(r.get("day") or ""),
        )
        it.tags.extend(str(t) for t in (r.get("tags") or []))
        return it

    hint = zpb.AgendaHint(
        project=str(d.get("project") or "gaius"),
        brief=str(d.get("brief") or ""),
        spoken=str(d.get("spoken") or ""),
        brief_at_ms=int(d.get("brief_at_ms") or 0),
        brief_id=str(d.get("brief_id") or ""),
        timezone=str(d.get("timezone") or DEFAULT_TIMEZONE),
        today=str(d.get("today") or ""),
        total_in_window=int(d.get("total_in_window") or 0),
        note=str(d.get("note") or ""),
    )
    for r in d.get("items") or []:
        hint.items.append(_item(r))
    if d.get("item"):
        hint.item.CopyFrom(_item(d["item"]))
    return hint
