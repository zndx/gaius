"""Week consolidation the cognition loop can carry forward.

Encode and MaxSim ground a week. BERTSubs may accept nothing. That is not
yet a week of understanding. Passing thoughts are momentary; the week's
investigation (``theta_investigation``) is a cognition process they provoke,
not a reduction of them. The row stores the well in ``content`` and the
standing implication in ``summary``. The daily loop reads the implication
whole. It does not read the well.

Which week is in force is the ISO slice (valid time), not when the row
landed (transaction time). A backfill of an earlier week must not displace
a later one. Landed time only breaks a tie inside the same slice.

The investigation does not mint classes and does not assert subsumption.
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

SYSTEM_PROMPT = (
    "You investigate one week of a knowledge agent's passing thoughts. "
    "Those thoughts are momentary inklings. They inspire understanding; "
    "they are not an outline to shorten. You may associate across inklings, "
    "earlier weeks, external sources, and class co-occurrence. Association "
    "is not assertion: do not mint classes, do not claim that one class is "
    "a subclass of another, and do not treat a metaphor or a repeated "
    "sentence as an identity. A frequent class is where admitted items sat, "
    "not a role to assign."
)


def local_name(iri: str) -> str:
    text = (iri or "").strip()
    if not text:
        return ""
    if "#" in text:
        return text.rsplit("#", 1)[-1].strip()
    return text.rstrip("/").rsplit("/", 1)[-1].strip()


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
    """The standing implication only. The well stays out of the daily loop.

    ``summary`` is that implication (KNOWN / STOP / OPEN). ``content`` is
    the investigation and is not spliced, truncated or otherwise.
    """
    if not row:
        return ""
    slice_id = str(row.get("slice_id") or "").strip() or "the last consolidated week"
    carry = str(row.get("summary") or "").strip()
    if not carry:
        return ""
    return (
        f"\n\nWEEK CONSOLIDATION ({slice_id}) — standing implication of that "
        "week's investigation, not a summary of passing thoughts. Use it. "
        f"Do not re-derive it:\n{carry}"
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
    context = json.dumps(
        {"slice_id": slice_id, "source": "theta_cycle", "form": "well"}
    )
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
            from gaius.engine.services.theta_investigation import (
                investigate_week,
                load_external_sources,
                load_prior_wells,
                notice_inklings,
            )

            inklings = notice_inklings(thoughts)
            if not inklings:
                raise RuntimeError(
                    f"{NOUNDERSTANDING} no cognition_thoughts to investigate in {slice_id}"
                )
            bindings = binding_histogram(groundings)
            prior = await load_prior_wells(conn, slice_id)
            sources = await load_external_sources(conn, slice_id, inklings)
            draft, raw, tokens, model = await investigate_week(
                client, slice_id, inklings, bindings, prior, sources
            )
            if draft is None:
                logger.warning(
                    "%s investigation rejected for %s: %s",
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
            clouds = [item["name"] for item in inklings if item.get("kind") == "cloud"]
            logger.info(
                "theta investigation %s thought=%s clouds=%s sources=%d prior=%s",
                slice_id,
                thought_id,
                ",".join(clouds[:8]),
                len(sources),
                ",".join(str(item.get("slice_id") or "") for item in prior),
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
