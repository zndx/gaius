"""The Thoughts Brief — "what have you been thinking about?", written before it is asked.

User (2026-09-07): the default for `/thoughts` should be a brief summary of
recent thoughts in the Agenda's framing, and the autonomous cognition cycle
should create it as part of its normal workflow so the reply is ready for an
instant return to the voice agent. And: NOT an Agenda item — "we want multiple
sources of content for conversation — the thoughts brief should be a Zettle
with prev and next links like our other thoughts."

So: one thinking Complete over the newest persisted thoughts, in the Agenda
Brief's framing (a summary OF the thoughts, useful to the reader, the model's
own structure within length norms), first person as the federation's
cognition. Two outputs in one answer: the written BRIEF and the plain-speech
SPOKEN form. Persisted to `cognition_briefs` AND as a zettelkasten note under
the day's scratch tree, prev/next-linked to the previous brief note exactly
like `thoughts_cycle` notes. Never written to the Agenda.

Fail-fast: a missing section, an empty answer or a store error raises
#CG.00000003.BRIEFFAIL with the evidence; nothing partial is written.
"""
from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from gaius.core.budgets import REASONING_MAX_TOKENS

logger = logging.getLogger(__name__)

GURU_BRIEFFAIL = "#CG.00000003.BRIEFFAIL"

NOTE_TYPE = "thoughts_brief"          # zettel filename suffix: <HHMMSS>_thoughts_brief.md
DEFAULT_WINDOW_HOURS = 24
DEFAULT_LIMIT = 12
BRIEF_MAX_CHARS = 1200
SPOKEN_MAX_CHARS = 700
_MARKDOWN_RE = re.compile(r"(^\s*[-*•]\s|^\s*#{1,6}\s|\*\*|`|\[[^\]]+\]\([^)]+\)|https?://)", re.M)

SYSTEM_PROMPT = (
    "You are the federation's cognition writing its own brief: a summary OF the "
    "thoughts you have recently persisted, in the first person, useful to a "
    "reader who asks 'what have you been thinking about?'. Summarise the "
    "thoughts — do not invent new ones, do not analyse from thin air."
)


def build_prompt(thoughts: list[dict[str, Any]], *, window_hours: int) -> str:
    blocks = []
    for i, t in enumerate(thoughts, 1):
        when = datetime.fromtimestamp(int(t["at_ms"]) / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
        text = t.get("summary") or t.get("excerpt") or ""
        blocks.append(
            f"{i}. [{t.get('kind') or 'thought'} · {when} UTC · salience {float(t.get('salience') or 0):.2f}] "
            f"{t.get('title') or 'Untitled'}\n   {text}"
        )
    body = "\n".join(blocks)
    return f"""Below are the {len(thoughts)} thoughts I persisted in the last {window_hours} hours, newest first.

{body}

Write my Thoughts Brief in exactly two sections, each starting on its own line with the label:

BRIEF:
The written brief, at most {BRIEF_MAX_CHARS} characters. First person. Say what is on my mind, the lines of thought and how they connect, the open questions, and what I should attend to next. Choose your own structure (plain prose, or a few short lines); stay within the length.

SPOKEN:
The same brief for a voice agent to say aloud: plain speech, four to six sentences, at most {SPOKEN_MAX_CHARS} characters. No markdown, no lists, no links, no code, no headings — words only.

Do not add anything after the SPOKEN section."""


def parse_brief(text: str) -> tuple[str, str]:
    """Extract (brief, spoken); both required, spoken must be plain speech."""
    raw = (text or "").strip()
    m = re.search(r"BRIEF:\s*(.*?)\n\s*SPOKEN:\s*(.*)\Z", raw, re.S | re.I)
    if not m:
        raise RuntimeError(
            f"{GURU_BRIEFFAIL} the brief answer lacks BRIEF:/SPOKEN: sections "
            f"(chars={len(raw)}); tail: {raw[-300:]!r}\n"
            "  Try: /thoughts cycle  (a new cycle rewrites the brief)"
        )
    brief = m.group(1).strip()
    spoken = m.group(2).strip()
    if not brief or not spoken:
        raise RuntimeError(f"{GURU_BRIEFFAIL} empty BRIEF or SPOKEN section; tail: {raw[-300:]!r}")
    if _MARKDOWN_RE.search(spoken):
        # Plain speech is a contract with the voice agent; strip what a model
        # habitually adds rather than fail the whole brief on a stray asterisk.
        spoken = _MARKDOWN_RE.sub("", spoken)
        spoken = re.sub(r"\s+", " ", spoken).strip()
    if len(brief) > BRIEF_MAX_CHARS * 2 or len(spoken) > SPOKEN_MAX_CHARS * 2:
        raise RuntimeError(
            f"{GURU_BRIEFFAIL} brief far over length (brief={len(brief)}, spoken={len(spoken)} chars)"
        )
    return brief, spoken


def _title_from(brief: str) -> str:
    """First sentence of the brief, ≤ 80 chars (a zettel title, not a fragment)."""
    first = brief.split("\n", 1)[0].strip().lstrip("#* ")
    m = re.match(r"(.{10,80}?[.!?])(\s|$)", first)
    title = m.group(1) if m else first
    if len(title) > 80:
        title = title[:80].rsplit(" ", 1)[0].rstrip("—–- ,.:;")
    return title.strip() or "Thoughts Brief"


# ── zettel ───────────────────────────────────────────────────────────────────
def save_brief_as_zettel(
    *,
    brief: str,
    spoken: str,
    thoughts: list[dict[str, Any]],
    cycle_id: str | None,
    brief_id: str,
    now: datetime,
    kb_root: Path | None = None,
) -> str:
    """Write the Brief as a KB note under scratch/<date>/, prev/next-linked to
    the previous brief note (bidirectional, like thoughts_cycle notes). Never an
    Agenda item. Returns the note path relative to the KB root."""
    from gaius.core.project_notes import _update_next_link, find_previous_project_note

    root = kb_root or Path(os.environ.get("GAIUS_KB_ROOT", "build/dev"))
    prev_note = find_previous_project_note(root, NOTE_TYPE)
    local = now.astimezone()  # the scratch tree is dated in local time like the other notes
    scratch_dir = root / "scratch" / local.strftime("%Y-%m-%d")
    scratch_dir.mkdir(parents=True, exist_ok=True)
    prev_link = ""
    if prev_note:
        try:
            prev_link = f"[[{prev_note.relative_to(root)}]]"
        except ValueError:
            prev_link = f"[[{prev_note.stem}]]"
    thought_notes = sorted({t.get("note_path") for t in thoughts if t.get("note_path")})
    lines = [
        "[[current/agents/cognition]]",
        f"prev: {prev_link}",
        "next:",
        "",
        f"# Thoughts Brief - {local.strftime('%H:%M:%S')}",
        "",
        "---",
        f"type: {NOTE_TYPE}",
        f"created: {now.isoformat()}",
        f"brief_id: {brief_id}",
        f"cycle_id: {cycle_id or ''}",
        f"thoughts_considered: {len(thoughts)}",
        "---",
        "",
        brief,
        "",
        "## Spoken",
        "",
        spoken,
        "",
        "## Considers",
        "",
    ]
    for t in thoughts:
        when = datetime.fromtimestamp(int(t["at_ms"]) / 1000, tz=timezone.utc).strftime("%m-%d %H:%M")
        lines.append(f"- {when} · {t.get('kind') or 'thought'} · {t.get('title') or 'Untitled'}")
    # Content, not navigation: the thoughts' own notes are references here;
    # prev:/next: above link ONLY the brief chain (user, 2026-09-07).
    if thought_notes:
        lines += ["", "Considers: " + " ".join(f"[[{p}]]" for p in thought_notes)]
    lines += ["", "---", "", "*Written by the cognition cycle. Edit, link, or dismiss as you wish.*", ""]
    note_path = scratch_dir / f"{local.strftime('%H%M%S')}_{NOTE_TYPE}.md"
    note_path.write_text("\n".join(lines))
    if prev_note and prev_note.exists():
        _update_next_link(prev_note, root, note_path)
    rel = str(note_path.relative_to(root))
    logger.info("thoughts brief zettel written: %s (prev %s)", rel, prev_link or "-")
    return rel


# ── compose ──────────────────────────────────────────────────────────────────
async def _complete(inference_client, prompt: str) -> tuple[str, int, str]:
    """One thinking Complete the way cognition_logic._generate_thoughts does it."""
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
    text, tokens = _validate_complete_response(response, context="thoughts_brief")
    model = ""
    if isinstance(response, dict):
        model = str(response.get("model") or response.get("model_name") or "")
    return text, int(tokens or 0), model


async def compose_thoughts_brief(
    db_pool,
    *,
    cycle_id: str | None = None,
    window_hours: int = DEFAULT_WINDOW_HOURS,
    limit: int = DEFAULT_LIMIT,
    now: datetime | None = None,
    inference_client=None,
    kb_root: Path | None = None,
) -> dict[str, Any]:
    """Read the newest thoughts, write the Brief (one thinking Complete),
    persist to cognition_briefs and as a prev/next-linked zettel. Fail-fast."""
    from gaius.engine.services.thoughts_hint import collect_thoughts

    now = now or datetime.now(timezone.utc)
    if db_pool is None:
        raise RuntimeError(f"{GURU_BRIEFFAIL} no database pool — cannot read thoughts or persist a brief")
    since_ms = int((now - timedelta(hours=window_hours)).timestamp() * 1000)
    found = await collect_thoughts(db_pool, limit=limit, since_ms=since_ms, now=now)
    thoughts = found.get("thoughts") or []
    if not thoughts:
        raise RuntimeError(
            f"{GURU_BRIEFFAIL} no thoughts in the last {window_hours} h to brief "
            f"({found.get('note') or 'store returned nothing'})"
        )
    if inference_client is None:
        from gaius.client import get_grpc_client

        inference_client = await get_grpc_client()
        if inference_client is None:
            raise RuntimeError(f"{GURU_BRIEFFAIL} engine gRPC client unavailable — the brief needs thinking")

    prompt = build_prompt(thoughts, window_hours=window_hours)
    text, tokens, model = await _complete(inference_client, prompt)
    if not (text or "").strip():
        raise RuntimeError(
            f"{GURU_BRIEFFAIL} thinking answered nothing (tokens={tokens}); the trace is not a brief"
        )
    brief, spoken = parse_brief(text)
    title = _title_from(brief)
    thought_ids = [t["id"] for t in thoughts if t.get("id")]
    at_values = [int(t["at_ms"]) for t in thoughts if t.get("at_ms")]
    window_start = datetime.fromtimestamp(min(at_values) / 1000, tz=timezone.utc) if at_values else now
    window_end = datetime.fromtimestamp(max(at_values) / 1000, tz=timezone.utc) if at_values else now
    context = {
        "max_tokens": REASONING_MAX_TOKENS,
        "response_chars": len(text),
        "prompt_chars": len(prompt),
        "window_hours": window_hours,
        "limit": limit,
    }
    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO cognition_briefs
                    (cycle_id, window_start, window_end, thought_ids, thoughts_considered,
                     title, body, spoken, model, tokens_used, generation_context)
                VALUES ($1::uuid, $2, $3, $4::uuid[], $5, $6, $7, $8, $9, $10, $11::jsonb)
                RETURNING id, created_at
                """,
                cycle_id,
                window_start,
                window_end,
                thought_ids,
                len(thoughts),
                title,
                brief,
                spoken,
                model or None,
                tokens,
                json.dumps(context),
            )
    except Exception as e:  # noqa: BLE001 — surfaced with the guru, never a half-written brief
        raise RuntimeError(f"{GURU_BRIEFFAIL} persisting the brief failed: {e}\n  Try: /health fix postgres") from e
    brief_id = str(row["id"])
    created_at = row["created_at"]
    note_path = save_brief_as_zettel(
        brief=brief, spoken=spoken, thoughts=thoughts, cycle_id=cycle_id, brief_id=brief_id,
        now=created_at if created_at.tzinfo else created_at.replace(tzinfo=timezone.utc), kb_root=kb_root,
    )
    async with db_pool.acquire() as conn:
        await conn.execute("UPDATE cognition_briefs SET note_path = $2 WHERE id = $1::uuid", brief_id, note_path)
    logger.info(
        "thoughts brief %s written: %d thoughts, %d chars written / %d spoken, note %s",
        brief_id, len(thoughts), len(brief), len(spoken), note_path,
    )
    return {
        "id": brief_id,
        "created_at": created_at,
        "title": title,
        "body": brief,
        "spoken": spoken,
        "thoughts_considered": len(thoughts),
        "thought_ids": thought_ids,
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
            SELECT id, created_at, cycle_id, title, body, spoken, thoughts_considered, note_path, model
            FROM cognition_briefs ORDER BY created_at DESC LIMIT 1
            """
        )
    if row is None:
        return None
    at = row["created_at"]
    if at.tzinfo is None:
        at = at.replace(tzinfo=timezone.utc)
    # The brief CHAIN: the neighbour before this one (the latest has no next).
    async with db_pool.acquire() as conn:
        prev = await conn.fetchrow(
            """
            SELECT id, note_path FROM cognition_briefs
            WHERE created_at < $1 ORDER BY created_at DESC LIMIT 1
            """,
            row["created_at"],
        )
    return {
        "id": str(row["id"]),
        "created_at": at,
        "at_ms": int(at.timestamp() * 1000),
        "cycle_id": str(row["cycle_id"]) if row["cycle_id"] else "",
        "title": row["title"] or "",
        "body": row["body"] or "",
        "spoken": row["spoken"] or "",
        "thoughts_considered": int(row["thoughts_considered"] or 0),
        "note_path": row["note_path"] or "",
        "model": row["model"] or "",
        "prev_brief_id": str(prev["id"]) if prev else "",
        "prev_note_path": (prev["note_path"] or "") if prev else "",
        "next_note_path": "",
    }


def next_cron_fire(schedule: str, now: datetime) -> datetime | None:
    """Next fire for the simple shapes pg_cron uses here (`M h1,h2,… * * *`,
    `*/N * * * *`, `M * * * *`); None for anything else."""
    parts = (schedule or "").split()
    if len(parts) != 5 or parts[2:] != ["*", "*", "*"]:
        return None
    minute_f, hour_f = parts[0], parts[1]
    try:
        if minute_f.startswith("*/"):
            step = int(minute_f[2:])
            base = now.replace(second=0, microsecond=0)
            nxt = base + timedelta(minutes=step - (base.minute % step) or step)
            return nxt if nxt > now else nxt + timedelta(minutes=step)
        minute = int(minute_f)
        hours = list(range(24)) if hour_f == "*" else sorted(int(h) for h in hour_f.split(","))
    except ValueError:
        return None
    base = now.replace(minute=minute, second=0, microsecond=0)
    for day in (0, 1):
        for h in hours:
            cand = (base + timedelta(days=day)).replace(hour=h)
            if cand > now:
                return cand
    return None


async def next_cycle_at(db_pool, now: datetime) -> datetime | None:
    """When the cognition-periodic enqueuer next fires, from cron.job."""
    if db_pool is None:
        return None
    try:
        async with db_pool.acquire() as conn:
            sched = await conn.fetchval(
                "SELECT schedule FROM cron.job WHERE jobname = 'cognition-periodic' AND active"
            )
    except Exception:  # noqa: BLE001 — cron.job may be unreadable; the note just says less
        return None
    return next_cron_fire(str(sched or ""), now) if sched else None
