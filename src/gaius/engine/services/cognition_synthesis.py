"""Incremental synthesis into cognition_buffer + agenda_entries.

Scratchpad constants live in cognition_buffer.py (one-next-question reserve).

Publishing (landed cards) + Prospects (FMP FIFO) + Ambient (HN buffer)
are refined by the thinking endpoint into cognition_buffer rows. An agenda
agent then emits Brief / Reminder / Session entries. Full prompts and
thinking traces go to HX ``llm.generations`` (Iceberg).

Guru: #COG.00000032.SYNTHFAIL
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

THINKING_CONTEXT_TOKENS = 262_144
# Held empty for one inbound question — not a conversation, not a session.
NEXT_QUESTION_RESERVE_TOKENS = 65_536
DEFAULT_SCRATCH_TOKEN_BUDGET = (
    THINKING_CONTEXT_TOKENS - NEXT_QUESTION_RESERVE_TOKENS
)

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

SYNTH_PROMPT = """You are Gaius cognition. Admitted Aperture windows (unique MaxSim
topic, 512-token spans with offsets) are below. The Ambient, Prospects, and
Publishing FIFOs still hold the full compacted text.

Optional tools (output these lines and nothing else, then wait):
SEARCH_BUFFER <ambient|prospects|publish> <query>
SEARCH_GURU <CODE>
  (unique meditation code, e.g. EN.00000031.FDWINGEST — for your RCA only;
   do not copy the code into SYNTHESIS/AGENDA bodies)

Agenda densities (do not over-produce):
- sessions: a few times a week, world events through Aperture
- reminders: short lists (content, ops follow-up, discretionary)
- briefs: expert-technical executive. Report root cause and operational
  facts (what failed, what to do). Do NOT pack guru meditation codes
  (#XX.00000000.MNEMONIC) into brief/reminder/session bodies — those codes
  are for your own RCA, not the executive text.

Or skip search and write:
SYNTHESIS:
<paragraphs>

AGENDA:
{{"briefs":[{{"title":"...","body":"..."}}],"reminders":[{{"title":"...","body":"- item\\n- item"}}],"sessions":[{{"title":"...","body":"..."}}]}}

Admitted windows:
{slices}
"""

SEARCH_RE = re.compile(
    r"^SEARCH_BUFFER\s+(ambient|prospects|publish)\s+(.+)$",
    re.IGNORECASE | re.MULTILINE,
)
GURU_SEARCH_RE = re.compile(
    r"^SEARCH_GURU\s+#?([A-Z]{2,5}\.\d{8}\.[A-Z0-9]+)\s*$",
    re.IGNORECASE | re.MULTILINE,
)
_REPO_ROOT = Path(__file__).resolve().parents[4]


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


def parse_search_requests(text: str) -> list[tuple[str, str]]:
    return [(m.group(1).lower(), m.group(2).strip()) for m in SEARCH_RE.finditer(text or "")]


def parse_guru_searches(text: str) -> list[str]:
    return [m.group(1).upper() for m in GURU_SEARCH_RE.finditer(text or "")]


def search_guru_in_repo(code: str, *, root: Path | None = None, max_hits: int = 16) -> str:
    """Ripgrep a unique guru code. For Thinking RCA, not executive copy."""
    code = code.lstrip("#").upper()
    if not re.fullmatch(r"[A-Z]{2,5}\.\d{8}\.[A-Z0-9]+", code):
        return f"[guru] invalid code {code!r}"
    root = root or _REPO_ROOT
    needle = f"#{code}"
    try:
        proc = subprocess.run(
            [
                "rg",
                "-n",
                "--no-heading",
                "-g",
                "!*.pyc",
                "-g",
                "!.devenv/**",
                "-g",
                "!**/generated/**",
                needle,
                "src",
                "tests",
                "features",
                "docs",
                "scripts",
                "config",
            ],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=8,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        return f"[guru] search failed: {e}"
    lines = [ln for ln in (proc.stdout or "").splitlines() if ln.strip()]
    if not lines:
        return f"[guru] no references to #{code}"
    clipped = lines[:max_hits]
    return f"[guru #{code}]\n" + "\n".join(clipped)


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
    publishing_buffer: Any | None,
    db_pool: Any | None = None,
) -> list[dict[str, str]]:
    """Admitted Aperture windows (offsets into full FIFO entries)."""
    from gaius.engine.services.axis_admit import AdmitStats, admitted_spans

    slices: list[dict[str, str]] = []
    stats = AdmitStats()
    axes: list[tuple[str, Any]] = []
    if ambient_buffer is not None:
        axes.append(("ambient", ambient_buffer))
    if prospects_service is not None:
        buf = getattr(prospects_service, "_buffer", None)
        if buf is not None:
            axes.append(("prospects", buf))
    if publishing_buffer is not None:
        axes.append(("publish", publishing_buffer))
    try:
        for axis, buf in axes:
            entries = await buf.snapshot()
            for e in entries:
                for span in admitted_spans(
                    e.content or "",
                    entry_id=getattr(e, "id", "") or "",
                    axis=axis,
                    stats=stats,
                ):
                    slices.append(
                        {
                            "source": axis,
                            "content": (
                                f"entry={span['entry_id'][:8]} "
                                f"off={span['start']}:{span['end']} "
                                f"topic={span['topic']}\n"
                                f"{span['content'][:1200]}"
                            ),
                        }
                    )
    except Exception as e:
        logger.error(
            "Aperture scan failed (buffers unchanged).\n"
            "  Guru: #SDG.00000006.STARVE\n"
            "  %s",
            e,
        )
    if stats.starved():
        logger.warning(
            "Aperture admitted no windows scanned=%s none=%s ambiguous=%s\n"
            "  Guru: #SDG.00000006.STARVE (inspect C/tau for GEPA)",
            stats.scanned,
            stats.none,
            stats.ambiguous,
        )
    return slices


async def search_axes(
    query: str,
    axis: str,
    *,
    ambient_buffer: Any | None,
    prospects_service: Any | None,
    publishing_buffer: Any | None,
) -> str:
    buf = None
    if axis == "ambient":
        buf = ambient_buffer
    elif axis == "prospects" and prospects_service is not None:
        buf = getattr(prospects_service, "_buffer", None)
    elif axis == "publish":
        buf = publishing_buffer
    if buf is None:
        return f"[{axis}] buffer not attached"
    hits = await buf.search(query, limit=6)
    if not hits:
        return f"[{axis}] no hits for {query!r}"
    parts = [
        f"[{axis} {getattr(h, 'id', '')[:8]}] {(h.content or '')[:800]}"
        for h in hits
    ]
    return "\n".join(parts)


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
    publishing_buffer: Any | None = None,
) -> dict[str, Any]:
    """Thinking synthesis → cognition_buffer + agenda. Health = this succeeded."""
    if db_pool is None:
        raise RuntimeError(f"{GURU}\n  no db pool")
    await ensure_tables(db_pool)
    slices = await gather_slices(
        ambient_buffer=ambient_buffer,
        prospects_service=prospects_service,
        publishing_buffer=publishing_buffer,
        db_pool=db_pool,
    )
    episode_id = str(uuid.uuid4())
    packed = "\n---\n".join(
        f"[{s['source']}]\n{s['content']}" for s in slices
    ) or "(no slices this cycle)"
    prompt = SYNTH_PROMPT.format(slices=packed[:12000])
    t0 = datetime.now(timezone.utc)
    output = ""
    thinking_trace = ""
    last = None
    for _round in range(3):
        last = await backend_router.complete(
            prompt=prompt,
            agent_alias="thinking",
            max_tokens=1024,
            temperature=0.4,
            task_type="cognition_synthesis",
            enable_thinking=True,
            reasoning_effort="low",
            preserve_thinking=True,
        )
        if getattr(last, "error", None):
            raise RuntimeError(f"{GURU}\n  complete: {last.error}")
        output = (getattr(last, "content", None) or "").strip()
        if not output:
            output = (getattr(last, "reasoning_content", None) or "").strip()
        thinking_trace = getattr(last, "reasoning_content", None) or thinking_trace
        if not output:
            raise RuntimeError(f"{GURU}\n  empty thinking output")
        reqs = parse_search_requests(output)
        gurus = parse_guru_searches(output)
        if "AGENDA:" in output or (not reqs and not gurus):
            break
        found: list[str] = []
        for axis, q in reqs[:4]:
            found.append(
                await search_axes(
                    q,
                    axis,
                    ambient_buffer=ambient_buffer,
                    prospects_service=prospects_service,
                    publishing_buffer=publishing_buffer,
                )
            )
        for code in gurus[:4]:
            found.append(
                await asyncio.to_thread(search_guru_in_repo, code)
            )
        prompt = (
            prompt
            + "\n\nSEARCH RESULTS:\n"
            + "\n".join(found)
            + "\n\nUse guru hits for RCA only. Do not pack codes into AGENDA. "
            "SEARCH_BUFFER / SEARCH_GURU again or write SYNTHESIS + AGENDA."
        )
    latency_ms = int((datetime.now(timezone.utc) - t0).total_seconds() * 1000)
    response = last
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
    from gaius.engine.services.agenda_policy import (
        DEFAULT_DENSITY,
        next_session_slots,
        session_invite_description,
        slots_remaining,
        strip_packed_guru,
        take_kind,
    )

    n = 0
    now = datetime.now(timezone.utc)
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT kind, count(*)::int AS n
              FROM agenda_entries
             WHERE status = 'open'
               AND created_at > NOW() - INTERVAL '7 days'
             GROUP BY 1
            """
        )
        open_counts = {str(r["kind"]): int(r["n"]) for r in rows}
        slots = slots_remaining(open_counts, DEFAULT_DENSITY)
        due_rows = await conn.fetch(
            """
            SELECT due_at FROM agenda_entries
             WHERE kind = 'session' AND status = 'open' AND due_at IS NOT NULL
            """
        )
        existing_dues = [r["due_at"] for r in due_rows if r["due_at"] is not None]
        session_times = next_session_slots(
            now, existing_dues, per_week=DEFAULT_DENSITY.sessions_per_week
        )
        planned = {
            "brief": take_kind(agenda.get("briefs") or [], kind="brief", slots=slots["brief"]),
            "reminder": take_kind(
                agenda.get("reminders") or [],
                kind="reminder",
                slots=slots["reminder"],
                reminder_items_max=DEFAULT_DENSITY.reminder_items_max,
            ),
            "session": take_kind(
                agenda.get("sessions") or [], kind="session", slots=slots["session"]
            ),
        }
        for i, item in enumerate(planned["session"]):
            due_at = session_times[i] if i < len(session_times) else None
            title = str(item.get("title") or "").strip()
            if not title:
                continue
            body = session_invite_description(
                title=title,
                body=strip_packed_guru(str(item.get("body") or "")),
                episode_id=episode_id,
                hx_generation_id=hx_id,
                due_at=due_at,
            )
            await conn.execute(
                """
                INSERT INTO agenda_entries
                    (kind, title, body, due_at, episode_id, hx_generation_id)
                VALUES ('session', $1, $2, $3, $4, $5)
                """,
                title[:240],
                body[:8000],
                due_at,
                episode_id,
                hx_id,
            )
            n += 1
        for kind in ("brief", "reminder"):
            for item in planned[kind]:
                title = str(item.get("title") or "").strip()
                if not title:
                    continue
                await conn.execute(
                    """
                    INSERT INTO agenda_entries
                        (kind, title, body, due_at, episode_id, hx_generation_id)
                    VALUES ($1, $2, $3, NULL, $4, $5)
                    """,
                    kind,
                    title[:240],
                    strip_packed_guru(str(item.get("body") or ""))[:4000],
                    episode_id,
                    hx_id,
                )
                n += 1
    return n
