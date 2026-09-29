"""Week consolidation the cognition loop can carry forward.

Encode and MaxSim ground a week. BERTSubs may accept nothing. That is not
yet a week of understanding: the cognition loop only sees the last day of
its own thoughts, so it re-derives the same pattern. A consolidation is the
week's understanding — what was established, what to stop repeating, and
how the admitted corpus sat on the certified TBox — written back as one
``cognition_thoughts`` row the next cycles must read. Which week is in
force is the ISO slice (valid time), not when the row landed
(transaction time). A backfill of an earlier week must not displace
a later one. Landed time only breaks a tie inside the same slice.

Class names in the prompt are existing bindings. This module does not mint
classes and does not assert subsumption.
"""

from __future__ import annotations

import json
import logging
import re
from collections import Counter
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

NOUNDERSTANDING = "#THETA.00000014.NOUNDERSTANDING"

_MIN_BODY = 240
_LABEL_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_SECTION_RE = re.compile(
    r"(?im)^(TITLE|SUMMARY|CARRY_FORWARD|STOP_REPEATING|APERTURE)\s*:\s*"
)
_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9_-]{4,}")

SYSTEM_PROMPT = (
    "You consolidate one week of a knowledge agent's cognition so later "
    "cycles and knowledge work can proceed from it. Class names you are "
    "given are existing ontology bindings of admitted items. Do not mint "
    "classes. Do not assert that one class is a subclass of another. "
    "Do not treat a repeated thought as a new discovery."
)


def local_name(iri: str) -> str:
    text = (iri or "").strip()
    if not text:
        return ""
    if "#" in text:
        return text.rsplit("#", 1)[-1].strip()
    return text.rstrip("/").rsplit("/", 1)[-1].strip()


def label_forms(label: str) -> set[str]:
    """CamelCase label and its spaced reading, for a cite check."""
    raw = (label or "").strip()
    if not raw:
        return set()
    spaced = _LABEL_RE.sub(" ", raw).lower()
    forms = {raw.lower(), spaced}
    if spaced.endswith("s") and len(spaced) > 4:
        forms.add(spaced[:-1])
    return {f for f in forms if f}


def binding_histogram(groundings: list[dict[str, Any]], limit: int = 12) -> list[tuple[str, int]]:
    """How often each TBox label grounded an admitted item this week."""
    counts: Counter[str] = Counter()
    for item in groundings or []:
        seen: set[str] = set()
        for pair in item.get("classes") or []:
            iri = pair[0] if isinstance(pair, (list, tuple)) else pair
            label = local_name(str(iri or ""))
            if not label or label in seen:
                continue
            # BFO_0000034 and ont00001180 are identifiers, not names the next
            # cycle can use. A named class has both cases (DataInput).
            if not (any(ch.islower() for ch in label) and any(ch.isupper() for ch in label)):
                continue
            seen.add(label)
            counts[label] += 1
    return counts.most_common(max(1, limit))


def collapse_thoughts(rows: list[dict[str, Any]], limit: int = 24) -> list[dict[str, Any]]:
    """One line per title, with how often the loop restated it."""
    grouped: dict[str, dict[str, Any]] = {}
    for row in rows or []:
        if str(row.get("thought_type") or "") == "consolidation":
            continue
        title = " ".join(str(row.get("title") or "").split())
        if not title:
            continue
        gist = " ".join(str(row.get("summary") or row.get("content") or "").split())
        key = title.casefold()
        salience = float(row.get("salience") or 0)
        slot = grouped.get(key)
        if slot is None:
            grouped[key] = {
                "title": title,
                "gist": gist[:180],
                "n": 1,
                "salience": salience,
            }
            continue
        slot["n"] += 1
        if salience >= float(slot["salience"]) and gist:
            slot["gist"] = gist[:180]
            slot["salience"] = salience
    ordered = sorted(
        grouped.values(),
        key=lambda s: (-int(s["n"]), -float(s["salience"]), str(s["title"])),
    )
    return ordered[: max(1, limit)]


def consolidation_prompt(
    slice_id: str,
    thoughts: list[dict[str, Any]],
    bindings: list[tuple[str, int]],
) -> str:
    """Ask for a week the next cognition cycle can use, not a new pattern."""
    lines = [
        f"Consolidate ISO week {slice_id} for the Gaius cognition loop.",
        "",
        "The loop will read this on later cycles. Write what the week",
        "established so knowledge work can go forward. Do not restate the",
        "loudest pattern as if it were new.",
        "",
        "What the loop kept saying (title, times restated, one line):",
    ]
    if not thoughts:
        lines.append("- (no thoughts)")
    for thought in thoughts:
        lines.append(
            f"- ({int(thought['n'])}×) {thought['title']}: {thought.get('gist') or ''}"
        )
    lines.extend(["", "What the week's admitted items grounded to on the certified TBox", "(existing classes; not new ones; not subclass claims):"])
    if not bindings:
        lines.append("- (no groundings)")
    for label, n in bindings:
        lines.append(f"- {label} ({n})")
    lines.extend(
        [
            "",
            "Write exactly these sections:",
            "TITLE: one line, at most 80 characters",
            "SUMMARY: one paragraph of what this week established",
            "CARRY_FORWARD: what the next cognition cycles and knowledge work should use",
            "STOP_REPEATING: what the loop should not derive again",
            "APERTURE: how those admitted-item classes sit relative to what the loop was saying",
        ]
    )
    return "\n".join(lines)


def _sections(text: str) -> dict[str, str]:
    matches = list(_SECTION_RE.finditer(text or ""))
    out: dict[str, str] = {}
    for i, match in enumerate(matches):
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        out[match.group(1).upper()] = " ".join(text[start:end].split())
    return out


def parse_consolidation(text: str) -> dict[str, str] | None:
    """TITLE / CARRY_FORWARD / STOP_REPEATING / APERTURE, or None."""
    parts = _sections(text or "")
    title = parts.get("TITLE") or ""
    carry = parts.get("CARRY_FORWARD") or ""
    stop = parts.get("STOP_REPEATING") or ""
    aperture = parts.get("APERTURE") or ""
    summary = parts.get("SUMMARY") or ""
    if not (title and carry and stop and aperture and summary):
        return None
    body = "\n".join(
        [
            f"TITLE: {title}",
            f"SUMMARY: {summary}",
            f"CARRY_FORWARD: {carry}",
            f"STOP_REPEATING: {stop}",
            f"APERTURE: {aperture}",
        ]
    )
    return {
        "title": title[:120],
        "summary": summary[:600],
        "content": body,
        "carry_forward": carry,
        "stop_repeating": stop,
        "aperture": aperture,
    }


def _asserts_subsumption(text: str) -> bool:
    """True when the draft claims subclass or subsumption, not when it refuses to.

    The prompt forbids the claim, so a careful reply says it is not asserting
    one. That refusal is not itself an assertion.
    """
    lowered = (text or "").lower()
    for match in re.finditer(r"subclass|subsum", lowered):
        window = lowered[max(0, match.start() - 48): match.start()]
        if re.search(r"\b(not|no|never|without|don't|do not)\b", window):
            continue
        return True
    return False


def understanding_holds(
    draft: dict[str, str] | None,
    thoughts: list[dict[str, Any]],
    bindings: list[tuple[str, int]],
) -> bool:
    """The draft cites this week's thoughts and at least one real binding.

    A generic essay, or a subclass claim, is not a consolidation.
    """
    if not draft:
        return False
    content = draft.get("content") or ""
    if len(content) < _MIN_BODY:
        return False
    if len(draft.get("carry_forward") or "") < 80:
        return False
    if len(draft.get("stop_repeating") or "") < 40:
        return False
    if _asserts_subsumption(content):
        return False
    lowered = content.lower()
    titles = [str(t.get("title") or "") for t in thoughts if t.get("title")]
    if titles and not any(title.lower() in lowered for title in titles):
        # A restated title may be shortened. Two content words still have to hit.
        words = {w.lower() for t in titles for w in _WORD_RE.findall(t)}
        if len(words & {w.lower() for w in _WORD_RE.findall(content)}) < 2:
            return False
    aperture = (draft.get("aperture") or "").lower()
    forms: set[str] = set()
    for label, _n in bindings:
        forms |= label_forms(label)
    if forms and not any(form in aperture for form in forms):
        return False
    return True


def current_iso_slice(now: datetime | None = None) -> str:
    """Zero-padded ISO week, the same shape as a Theta ``slice_id``.

    UTC, matching the encode clock. Weeks are ``W01``–``W53`` so string
    order is ISO order, including the year boundary.
    """
    if now is None:
        now = datetime.now(timezone.utc)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    iso = now.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def _mapping_get(row: Any, key: str) -> Any:
    if isinstance(row, dict):
        return row.get(key)
    try:
        return row[key]
    except (KeyError, IndexError, TypeError):
        return None


def _landed_sort_key(value: Any) -> tuple[int, str]:
    """Later transaction time sorts higher. A missing time loses the tie."""
    if value is None:
        return (0, "")
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return (1, value.astimezone(timezone.utc).isoformat())
    text = str(value).strip()
    if not text:
        return (0, "")
    return (1, text)


def choose_latest_consolidation(
    rows: list[Any] | None,
    as_of_slice: str,
) -> dict[str, Any] | None:
    """Week in force: greatest ISO slice at or before ``as_of_slice``.

    Valid time is ``slice_id``. ``created_at`` is transaction time and
    only chooses among revisions of that same slice. A slice after
    ``as_of_slice`` is not in force. Empty slice ids are not a week.
    """
    as_of = (as_of_slice or "").strip()
    best: tuple[str, tuple[int, str], dict[str, Any]] | None = None
    for row in rows or []:
        slice_id = str(_mapping_get(row, "slice_id") or "").strip()
        if not slice_id or not as_of or slice_id > as_of:
            continue
        landed = _landed_sort_key(_mapping_get(row, "created_at"))
        chosen = dict(row)
        if best is None or (slice_id, landed) > (best[0], best[1]):
            best = (slice_id, landed, chosen)
    return None if best is None else best[2]


def consolidation_prompt_section(row: dict[str, Any] | None) -> str:
    """Block spliced into a cognition cycle so the week is not re-derived.

    The full sections travel, not the summary alone: STOP_REPEATING is what
    keeps the next cycle from publishing the same pattern again.
    """
    if not row:
        return ""
    slice_id = str(row.get("slice_id") or "").strip() or "the last consolidated week"
    content = str(row.get("content") or "").strip()
    summary = " ".join(str(row.get("summary") or "").split())
    body = content or summary
    if not body:
        return ""
    return (
        f"\n\nWEEK CONSOLIDATION ({slice_id}) — already established. "
        "Use it for what you do next. Do not re-derive it as a new pattern "
        "or a new curiosity. Recent thoughts that repeat it are the loop "
        f"failing to carry it; do not emit another one:\n{body[:2000]}"
    )


def complete_text(response: dict[str, Any]) -> tuple[str, int]:
    from gaius.engine.proto_types import CompleteResponseDTO

    dto = CompleteResponseDTO.from_proto_dict(response)
    return dto.text or "", int(dto.tokens_used or 0)


async def _complete(client: Any, prompt: str) -> tuple[str, int, str]:
    from gaius.core.budgets import REASONING_MAX_TOKENS

    response = await client.call(
        service="Scheduler",
        action="complete",
        params={
            "prompt": prompt,
            "system_prompt": SYSTEM_PROMPT,
            "agent": "thinking",
            "max_tokens": REASONING_MAX_TOKENS,
        },
    )
    text, tokens = complete_text(response if isinstance(response, dict) else {})
    model = ""
    if isinstance(response, dict):
        model = str(response.get("model") or "")
    return text, tokens, model


async def draft_week(
    client: Any,
    slice_id: str,
    thoughts: list[dict[str, Any]],
    bindings: list[tuple[str, int]],
) -> tuple[dict[str, str] | None, str, int, str]:
    """One thinking pass, then one retry that names the rejected draft.

    Returns (held draft or None, last raw text, tokens, model).
    """
    prompt = consolidation_prompt(slice_id, thoughts, bindings)
    text, tokens, model = await _complete(client, prompt)
    draft = parse_consolidation(text)
    if understanding_holds(draft, thoughts, bindings):
        return draft, text, tokens, model
    retry = (
        prompt
        + "\n\nThe previous reply was not usable. Cite the thought titles "
        "you were given, name at least one TBox label in APERTURE using "
        "that label, and do not assert subclass or subsumption.\n\n"
        + (text or "")[:1500]
    )
    text2, tokens2, model2 = await _complete(client, retry)
    draft = parse_consolidation(text2)
    spent = tokens + tokens2
    used = model2 or model
    if understanding_holds(draft, thoughts, bindings):
        return draft, text2, spent, used
    return None, text2, spent, used


async def store_consolidation(
    conn: Any,
    slice_id: str,
    draft: dict[str, str],
    *,
    model: str = "",
    tokens: int = 0,
) -> str:
    """Insert or replace the active consolidation thought for this slice."""
    existing = await conn.fetchval(
        """
        SELECT id FROM cognition_thoughts
         WHERE thought_type = 'consolidation'
           AND status = 'active'
           AND generation_context->>'slice_id' = $1
         ORDER BY created_at DESC
         LIMIT 1
        """,
        slice_id,
    )
    context = json.dumps({"slice_id": slice_id, "source": "theta_cycle"})
    if existing is not None:
        await conn.execute(
            """
            UPDATE cognition_thoughts
               SET title = $2,
                   summary = $3,
                   content = $4,
                   generator_model = $5,
                   tokens_used = $6,
                   updated_at = NOW(),
                   generation_context = $7::jsonb
             WHERE id = $1
            """,
            existing,
            draft["title"],
            draft["summary"],
            draft["content"],
            model or None,
            int(tokens or 0),
            context,
        )
        return str(existing)
    new_id = await conn.fetchval(
        """
        INSERT INTO cognition_thoughts (
            thought_type, status, title, content, summary,
            salience, confidence, novelty, profile_name,
            generator_model, tokens_used, generation_context
        )
        VALUES (
            'consolidation', 'active', $1, $2, $3,
            0.9, 0.6, 0.4, 'theta',
            $4, $5, $6::jsonb
        )
        RETURNING id
        """,
        draft["title"],
        draft["content"],
        draft["summary"],
        model or None,
        int(tokens or 0),
        context,
    )
    return str(new_id)


async def load_groundings(conn: Any, slice_id: str) -> list[dict[str, Any]]:
    raw = await conn.fetchval(
        """
        SELECT metadata->'item_groundings'
          FROM theta_consolidation_runs
         WHERE slice_id = $1
           AND metadata ? 'item_groundings'
         ORDER BY id DESC
         LIMIT 1
        """,
        slice_id,
    )
    if raw is None:
        return []
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return []
    return list(raw or [])


async def close_week_understanding(
    dsn: str,
    slice_id: str,
    *,
    thoughts: list[dict[str, Any]] | None = None,
    groundings: list[dict[str, Any]] | None = None,
    client: Any = None,
) -> str:
    """Write the week's consolidation thought. Raise if it does not hold.

    Returns the cognition_thoughts id. Does not mark the ledger row.
    """
    import asyncpg

    if client is None:
        from gaius.client import get_grpc_client

        client = await get_grpc_client()
    pool = await asyncpg.create_pool(dsn)
    try:
        async with pool.acquire() as conn:
            if thoughts is None:
                from gaius.engine.services.theta_cycle import load_thoughts

                thoughts = await load_thoughts(conn, slice_id)
            if groundings is None:
                groundings = await load_groundings(conn, slice_id)
            collapsed = collapse_thoughts(thoughts)
            bindings = binding_histogram(groundings)
            if not collapsed:
                raise RuntimeError(
                    f"{NOUNDERSTANDING} no cognition_thoughts to consolidate in {slice_id}"
                )
            draft, raw, tokens, model = await draft_week(
                client, slice_id, collapsed, bindings
            )
            if draft is None:
                logger.warning(
                    "%s consolidation draft rejected for %s: %s",
                    NOUNDERSTANDING,
                    slice_id,
                    (raw or "")[:400],
                )
                raise RuntimeError(
                    f"{NOUNDERSTANDING} week {slice_id} did not produce an understanding "
                    "the cognition loop can carry"
                )
            thought_id = await store_consolidation(
                conn, slice_id, draft, model=model, tokens=tokens
            )
            logger.info(
                "theta consolidation %s thought=%s titles=%d bindings=%d",
                slice_id,
                thought_id,
                len(collapsed),
                len(bindings),
            )
            return thought_id
    finally:
        await pool.close()


async def attach_week_understanding(
    dsn: str,
    slice_id: str,
    window: str,
    result: dict[str, Any],
    *,
    client: Any = None,
) -> dict[str, Any]:
    """Write the understanding when this run closes the week.

    A day that is not the seventh is unchanged. A run that already failed
    (no thoughts, no pairs, ontology) is unchanged — this does not turn
    NOPAIRS into a success. A closing run whose draft does not hold fails
    as NOUNDERSTANDING.
    """
    out = dict(result or {})
    if not out.get("success") or out.get("guru_code"):
        return out
    from gaius.engine.services.theta_cycle import run_closes_week

    windows = [str(w) for w in ((out.get("metadata") or {}).get("windows") or [])]
    if not run_closes_week(window, windows, slice_id):
        return out
    try:
        thought_id = await close_week_understanding(
            dsn, slice_id, client=client
        )
    except Exception as exc:  # noqa: BLE001 — the ledger must record the miss
        err = str(exc).strip() or NOUNDERSTANDING
        if NOUNDERSTANDING not in err:
            err = f"{NOUNDERSTANDING} {err}"
        out["success"] = False
        out["error"] = err
        out["guru_code"] = NOUNDERSTANDING
        out["stage"] = "understand"
        return out
    out["consolidation_thought_id"] = thought_id
    out["stage"] = "understand"
    return out


async def seal_blank_week(dsn: str, slice_id: str, thought_id: str) -> int | None:
    """A coverage-only CONSFAIL becomes completed once the understanding exists.

    Other failures (ontology, encode, no thoughts) stay failed.
    """
    import asyncpg

    from gaius.engine.services.theta_cycle import BLANK_RESULT

    pool = await asyncpg.create_pool(dsn)
    try:
        async with pool.acquire() as conn:
            sealed = await conn.fetchval(
                """
                UPDATE theta_consolidation_runs
                   SET status = 'completed',
                       completed_at = COALESCE(completed_at, NOW()),
                       error = NULL,
                       metadata = COALESCE(metadata, '{}'::jsonb)
                           || jsonb_build_object('consolidation_thought_id', $2::text)
                 WHERE id = (
                     SELECT id FROM theta_consolidation_runs
                      WHERE slice_id = $1
                        AND status = 'failed'
                        AND error = $3
                      ORDER BY id DESC
                      LIMIT 1
                 )
                RETURNING id
                """,
                slice_id,
                thought_id,
                BLANK_RESULT,
            )
            return int(sealed) if sealed is not None else None
    finally:
        await pool.close()
