"""Incremental Cognition buffer: world slices → Thinking synthesis → agenda.

Publishing (landed cards) + Prospects (FMP FIFO) + Ambient (HN buffer)
are refined by the thinking endpoint into cognition_buffer rows. An agenda
agent then emits Brief / Reminder / Session entries. Full prompts and
thinking traces go to HX ``llm.generations`` (Iceberg).

Guru: #COG.00000032.SYNTHFAIL
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

GURU = (
    "Cognition synthesis via thinking failed.\n"
    "  Guru: #COG.00000032.SYNTHFAIL\n"
    "  Try: /gpu status thinking; psql … SELECT count(*) FROM cognition_buffer"
)

ENSURE_SQL = """
CREATE TABLE IF NOT EXISTS cognition_buffer (
    id BIGSERIAL PRIMARY KEY,
    episode_id TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('slice', 'synthesis')),
    source TEXT NOT NULL,
    content TEXT NOT NULL,
    hx_generation_id TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS agenda_entries (
    id BIGSERIAL PRIMARY KEY,
    kind TEXT NOT NULL CHECK (kind IN ('brief', 'reminder', 'session')),
    title TEXT NOT NULL,
    body TEXT NOT NULL DEFAULT '',
    due_at TIMESTAMPTZ,
    episode_id TEXT NOT NULL,
    hx_generation_id TEXT,
    status TEXT NOT NULL DEFAULT 'open',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""

SYNTH_PROMPT = """You are Gaius cognition. Refine these real-world slices into one
incremental synthesis (what is in flight vs what landed). Then emit agenda JSON.

Slices:
{slices}

Rules:
- Use only these slices. No toy coding problems.
- Agenda kinds: brief (situation), reminder (dated follow-up), session (work block).
- Reply as:
SYNTHESIS:
<paragraphs>

AGENDA:
{{"briefs":[{{"title":"...","body":"..."}}],"reminders":[{{"title":"...","body":"...","due_at":null}}],"sessions":[{{"title":"...","body":"..."}}]}}
"""


def parse_agenda_payload(text: str) -> dict[str, list[dict[str, Any]]]:
    """Extract agenda JSON from a synthesis completion. Fail-fast if missing."""
    blob = text
    m = re.search(r"AGENDA:\s*(\{.*\})\s*$", text, re.DOTALL | re.IGNORECASE)
    if m:
        blob = m.group(1)
    else:
        m = re.search(r"\{[\s\S]*\"briefs\"[\s\S]*\}", text)
        if m:
            blob = m.group(0)
    try:
        data = json.loads(blob)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"{GURU}\n  agenda JSON: {e}\n  text={text[:400]!r}") from e
    if not isinstance(data, dict) or "briefs" not in data:
        raise RuntimeError(f"{GURU}\n  agenda missing briefs: {text[:400]!r}")
    for key in ("briefs", "reminders", "sessions"):
        data.setdefault(key, [])
        if not isinstance(data[key], list):
            data[key] = []
    return data


def synthesis_body(text: str) -> str:
    m = re.search(r"SYNTHESIS:\s*(.*?)\s*AGENDA:", text, re.DOTALL | re.IGNORECASE)
    if m:
        return m.group(1).strip()
    return text.strip()


async def ensure_tables(pool: Any) -> None:
    async with pool.acquire() as conn:
        await conn.execute(ENSURE_SQL)


async def gather_slices(
    *,
    ambient_buffer: Any | None,
    prospects_service: Any | None,
    db_pool: Any | None,
) -> list[dict[str, str]]:
    """Collect short slices. Empty is allowed; synthesis then says so."""
    slices: list[dict[str, str]] = []
    if ambient_buffer is not None:
        for role_name in ("summary", "content"):
            try:
                from gaius.engine.services.ambient_buffer import BufferRole

                role = BufferRole.SUMMARY if role_name == "summary" else BufferRole.CONTENT
                entries = await ambient_buffer.get_entries_by_role(role, limit=6)
            except Exception:
                entries = []
            for e in entries:
                slices.append(
                    {
                        "source": "ambient",
                        "content": (e.content or "")[:1200],
                    }
                )
    if prospects_service is not None:
        buf = getattr(prospects_service, "_buffer", None)
        if buf is not None:
            try:
                from gaius.engine.services.ambient_buffer import BufferRole

                entries = await buf.get_entries_by_role(BufferRole.SUMMARY, limit=4)
                if not entries:
                    entries = await buf.get_entries_by_role(BufferRole.CONTENT, limit=4)
            except Exception:
                entries = []
            for e in entries:
                slices.append(
                    {
                        "source": "prospects",
                        "content": (e.content or "")[:1200],
                    }
                )
    if db_pool is not None:
        try:
            async with db_pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT title, COALESCE(summary, '') AS summary
                      FROM collections.cards
                     WHERE status = 'published'
                     ORDER BY published_at DESC NULLS LAST
                     LIMIT 6
                    """
                )
            for r in rows:
                slices.append(
                    {
                        "source": "publish",
                        "content": f"{r['title']}\n{r['summary']}"[:1200],
                    }
                )
        except Exception as e:
            logger.warning("publish slices skipped: %s", e)
    return slices


async def store_hx_generation(
    *,
    generation_id: str,
    prompt: str,
    output: str,
    thinking_trace: str,
    model_name: str,
    input_tokens: int,
    output_tokens: int,
    latency_ms: int,
    summary_type: str,
) -> None:
    import pyarrow as pa
    from gaius.hx.catalog import get_catalog
    from gaius.hx.tables import get_llm_generation_table

    catalog = get_catalog()
    table = get_llm_generation_table(catalog)
    now = datetime.now(timezone.utc)
    arrow_schema = pa.schema(
        [
            pa.field("id", pa.string(), nullable=False),
            pa.field("collection_id", pa.string(), nullable=True),
            pa.field("summary_type", pa.string(), nullable=False),
            pa.field("prompt", pa.string(), nullable=False),
            pa.field("output", pa.string(), nullable=False),
            pa.field("thinking_trace", pa.string(), nullable=True),
            pa.field("model_name", pa.string(), nullable=False),
            pa.field("input_tokens", pa.int64(), nullable=True),
            pa.field("output_tokens", pa.int64(), nullable=True),
            pa.field("latency_ms", pa.int64(), nullable=True),
            pa.field("generated_at", pa.timestamp("us", tz="UTC"), nullable=False),
        ]
    )
    record = pa.table(
        {
            "id": [generation_id],
            "collection_id": [None],
            "summary_type": [summary_type],
            "prompt": [prompt],
            "output": [output],
            "thinking_trace": [thinking_trace or ""],
            "model_name": [model_name],
            "input_tokens": [int(input_tokens)],
            "output_tokens": [int(output_tokens)],
            "latency_ms": [int(latency_ms)],
            "generated_at": [now],
        },
        schema=arrow_schema,
    )
    table.append(record)


async def run_synthesis_cycle(
    *,
    backend_router: Any,
    db_pool: Any,
    ambient_buffer: Any | None = None,
    prospects_service: Any | None = None,
) -> dict[str, Any]:
    """Thinking synthesis → cognition_buffer + agenda. Health = this succeeded."""
    if db_pool is None:
        raise RuntimeError(f"{GURU}\n  no db pool")
    await ensure_tables(db_pool)
    slices = await gather_slices(
        ambient_buffer=ambient_buffer,
        prospects_service=prospects_service,
        db_pool=db_pool,
    )
    episode_id = str(uuid.uuid4())
    packed = "\n---\n".join(
        f"[{s['source']}]\n{s['content']}" for s in slices
    ) or "(no slices this cycle)"
    prompt = SYNTH_PROMPT.format(slices=packed[:12000])
    t0 = datetime.now(timezone.utc)
    response = await backend_router.complete(
        prompt=prompt,
        agent_alias="thinking",
        max_tokens=1024,
        temperature=0.4,
        task_type="cognition_synthesis",
        enable_thinking=True,
        reasoning_effort="low",
        preserve_thinking=True,
    )
    latency_ms = int((datetime.now(timezone.utc) - t0).total_seconds() * 1000)
    if getattr(response, "error", None):
        raise RuntimeError(f"{GURU}\n  complete: {response.error}")
    output = (getattr(response, "content", None) or "").strip()
    if not output:
        output = (getattr(response, "reasoning_content", None) or "").strip()
    if not output:
        raise RuntimeError(f"{GURU}\n  empty thinking output")
    thinking_trace = getattr(response, "reasoning_content", None) or ""
    hx_id = str(uuid.uuid4())
    try:
        await store_hx_generation(
            generation_id=hx_id,
            prompt=prompt,
            output=output,
            thinking_trace=thinking_trace,
            model_name=getattr(response, "model", None) or "thinking",
            input_tokens=int(getattr(response, "input_tokens", 0) or 0),
            output_tokens=int(getattr(response, "output_tokens", 0) or 0),
            latency_ms=latency_ms,
            summary_type="cognition_synthesis",
        )
    except Exception as e:
        raise RuntimeError(f"{GURU}\n  HX llm.generations: {e}") from e

    synth_text = synthesis_body(output)
    async with db_pool.acquire() as conn:
        for s in slices:
            await conn.execute(
                """
                INSERT INTO cognition_buffer
                    (episode_id, kind, source, content, hx_generation_id, metadata)
                VALUES ($1, 'slice', $2, $3, $4, '{}'::jsonb)
                """,
                episode_id,
                s["source"],
                s["content"],
                hx_id,
            )
        await conn.execute(
            """
            INSERT INTO cognition_buffer
                (episode_id, kind, source, content, hx_generation_id, metadata)
            VALUES ($1, 'synthesis', 'thinking', $2, $3, $4::jsonb)
            """,
            episode_id,
            synth_text,
            hx_id,
            json.dumps({"latency_ms": latency_ms}),
        )

    agenda = parse_agenda_payload(output)
    n_agenda = await insert_agenda(db_pool, episode_id, hx_id, agenda)
    logger.info(
        "cognition synthesis episode=%s slices=%s agenda=%s hx=%s ms=%s",
        episode_id,
        len(slices),
        n_agenda,
        hx_id,
        latency_ms,
    )
    return {
        "episode_id": episode_id,
        "hx_generation_id": hx_id,
        "slices": len(slices),
        "agenda": n_agenda,
        "latency_ms": latency_ms,
        "success": True,
    }


async def insert_agenda(
    pool: Any,
    episode_id: str,
    hx_id: str,
    agenda: dict[str, list[dict[str, Any]]],
) -> int:
    n = 0
    kind_map = (
        ("briefs", "brief"),
        ("reminders", "reminder"),
        ("sessions", "session"),
    )
    async with pool.acquire() as conn:
        for key, kind in kind_map:
            for item in agenda.get(key) or []:
                title = str(item.get("title") or "").strip()
                if not title:
                    continue
                body = str(item.get("body") or "")
                due = item.get("due_at") or item.get("due_at_iso")
                due_at = None
                if due:
                    try:
                        due_at = datetime.fromisoformat(str(due).replace("Z", "+00:00"))
                    except ValueError:
                        due_at = None
                await conn.execute(
                    """
                    INSERT INTO agenda_entries
                        (kind, title, body, due_at, episode_id, hx_generation_id)
                    VALUES ($1, $2, $3, $4, $5, $6)
                    """,
                    kind,
                    title[:240],
                    body[:4000],
                    due_at,
                    episode_id,
                    hx_id,
                )
                n += 1
    return n
