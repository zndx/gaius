"""ServerQuery kind=THOUGHTS — "what have you been thinking about?" as CONTENT.

The day-one question. `CognitionHint` (kind=COGNITION) is the overview — counts
and buckets; this is the substance: the newest persisted thoughts of THIS
engine's cognition, bounded and newest first, so a peer's agent (the Hermes
voice loop, another project's briefing) can talk about them in its own words.

Two hops, never one: a local process asks its local engine, which asks the
peer engine. Nothing here is a search — the KB and the gaius UI remain the
deep surface. Honest when empty or idle: the `note` says so; no placeholder
thoughts, ever.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)

GURU_NOPOOL = "#CG.00000001.NOPOOL"
GURU_STOREFAIL = "#CG.00000002.STOREFAIL"

DEFAULT_LIMIT = 6
MAX_LIMIT = 12
DEFAULT_WINDOW = timedelta(days=7)
SUMMARY_CHARS = 600
EXCERPT_CHARS = 1200
IDLE_AFTER = timedelta(hours=6)  # the cognition cadence is 4 h; past this, say so

# thought_type values the store uses today (a filter, not a validator).
KNOWN_KINDS = ("pattern", "connection", "question", "reflection", "audit", "observation")


def _clip(text: str | None, n: int) -> str:
    s = (text or "").strip()
    if len(s) <= n:
        return s
    cut = s[: n - 1].rsplit(" ", 1)[0]
    return cut + "…"


def _ms(dt: datetime | None) -> int:
    if dt is None:
        return 0
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def _row_to_thought(row: Any) -> dict[str, Any]:
    summary = _clip(row["summary"], SUMMARY_CHARS)
    content = (row["content"] or "").strip()
    # The excerpt carries the content only when the summary does not already say it.
    excerpt = ""
    if content and (not summary or len(content) > len(summary) + 80):
        excerpt = _clip(content, EXCERPT_CHARS)
    if not summary and excerpt:
        summary, excerpt = _clip(content, SUMMARY_CHARS), excerpt
    return {
        "id": str(row["id"]),
        "at_ms": _ms(row["created_at"]),
        "kind": str(row["thought_type"] or ""),
        "title": _clip(row["title"], 200),
        "summary": summary,
        "excerpt": excerpt,
        "domains": [str(d) for d in (row["domains"] or []) if d],
        "salience": float(row["salience"] or 0.0),
        "chain_id": str(row["thought_chain_id"] or ""),
        "generation": int(row["generation"] or 0),
        "note_path": str(row["note_path"] or ""),
        "profile": str(row["profile_name"] or ""),
        "model": str(row["generator_model"] or ""),
    }


async def collect_thoughts(
    pool: Any,
    *,
    limit: int = 0,
    since_ms: int = 0,
    stream: str = "",
    now: datetime | None = None,
) -> dict[str, Any]:
    """Plain-dict form of the hint (the servicer converts to proto).

    limit: 0 → DEFAULT_LIMIT, capped at MAX_LIMIT. since_ms: 0 → the default
    window. stream: thought_type filter ("" = all).
    """
    now = now or datetime.now(timezone.utc)
    n = min(int(limit) or DEFAULT_LIMIT, MAX_LIMIT)
    since = (
        datetime.fromtimestamp(int(since_ms) / 1000, tz=timezone.utc)
        if since_ms
        else now - DEFAULT_WINDOW
    )
    kind = (stream or "").strip().lower()
    out: dict[str, Any] = {
        "project": "gaius",
        "thoughts": [],
        "total_in_window": 0,
        "newest_ms": 0,
        "window_ms": max(0, int((now - since).total_seconds() * 1000)),
        "cycles_in_window": 0,
        "note": "",
    }
    if pool is None:
        out["note"] = f"{GURU_NOPOOL} cognition store unavailable (engine still booting?)\n  Try: /health"
        return out
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, thought_type, title, content, summary, domains, salience,
                       thought_chain_id, generation, note_path, profile_name,
                       generator_model, created_at
                FROM cognition_thoughts
                WHERE created_at >= $1
                  AND COALESCE(status, '') NOT IN ('expired', 'archived', 'rejected')
                  AND ($2 = '' OR lower(thought_type) = $2)
                ORDER BY created_at DESC
                LIMIT $3
                """,
                since,
                kind,
                n,
            )
            total = await conn.fetchval(
                """
                SELECT count(*) FROM cognition_thoughts
                WHERE created_at >= $1
                  AND COALESCE(status, '') NOT IN ('expired', 'archived', 'rejected')
                  AND ($2 = '' OR lower(thought_type) = $2)
                """,
                since,
                kind,
            )
            newest = await conn.fetchval("SELECT max(created_at) FROM cognition_thoughts")
            try:
                cycles = await conn.fetchval(
                    "SELECT count(*) FROM cognition_cycles WHERE started_at >= $1", since
                )
            except Exception:  # noqa: BLE001 — the cycles table is optional bookkeeping
                cycles = 0
    except Exception as e:  # noqa: BLE001 — surfaced in the note, never a fake thought
        logger.warning("%s cognition_thoughts read failed: %s", GURU_STOREFAIL, e)
        out["note"] = f"{GURU_STOREFAIL} cognition store read failed: {e}\n  Try: /health fix postgres"
        return out

    out["thoughts"] = [_row_to_thought(r) for r in rows]
    out["total_in_window"] = int(total or 0)
    out["newest_ms"] = _ms(newest)
    out["cycles_in_window"] = int(cycles or 0)
    if newest is None:
        out["note"] = "store empty — no thoughts have been persisted yet"
    else:
        newest_dt = newest if newest.tzinfo else newest.replace(tzinfo=timezone.utc)
        age = now - newest_dt
        if age > IDLE_AFTER:
            hours = int(age.total_seconds() // 3600)
            out["note"] = f"cognition idle: newest thought is {hours} h old (cadence 4 h)"
        elif not out["thoughts"]:
            out["note"] = "no thoughts match the filter in this window"
    return out


def to_proto(d: dict[str, Any]):
    """Dict → zndx.engine.v1.ThoughtsHint."""
    from gaius.engine.generated.zndx.engine.v1 import engine_pb2 as zpb

    hint = zpb.ThoughtsHint(
        project=str(d.get("project") or "gaius"),
        total_in_window=int(d.get("total_in_window") or 0),
        newest_ms=int(d.get("newest_ms") or 0),
        window_ms=int(d.get("window_ms") or 0),
        cycles_in_window=int(d.get("cycles_in_window") or 0),
        note=str(d.get("note") or ""),
    )
    for t in d.get("thoughts") or []:
        th = zpb.Thought(
            id=str(t.get("id") or ""),
            at_ms=int(t.get("at_ms") or 0),
            kind=str(t.get("kind") or ""),
            title=str(t.get("title") or ""),
            summary=str(t.get("summary") or ""),
            excerpt=str(t.get("excerpt") or ""),
            salience=float(t.get("salience") or 0.0),
            chain_id=str(t.get("chain_id") or ""),
            generation=int(t.get("generation") or 0),
            note_path=str(t.get("note_path") or ""),
            profile=str(t.get("profile") or ""),
            model=str(t.get("model") or ""),
        )
        th.domains.extend(str(x) for x in (t.get("domains") or []))
        hint.thoughts.append(th)
    return hint
