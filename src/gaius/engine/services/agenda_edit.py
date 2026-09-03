"""Multi-turn Agenda note editing via the ACP thinking agent.

Later rounds of content are INCORPORATED into an existing note by the
thinking model through tool-mediated file access — read first, then
targeted exact-replacement edits — never by regenerating the note or
jamming its content into a prompt. The on-disk note is the source of
truth; the agent's edit tool fails loudly on ambiguous spans and the
protocol is re-read-and-retry (the Pi-class editing contract: matches
against the original snapshot, hard errors instead of close-enough
patches).

Why the ACP thinking lane: grok-build driven by local Qwen3.8-27B via
Engine/Complete is an already-sanctioned in-engine agent loop with
strict read/edit tools (the health observer's RCA rides it). The
native alternative — structured messages + tools[] on gRPC Complete —
is the planned end-state; today's Complete flattens transcripts, which
breaks tool loops (see engine_client.complete).

Proof case (2026-09-02): the publish Brief day-item. Each publish slot
merges its cards into the day's existing Brief instead of the upsert
clobbering whatever a prior slot wrote.

Failure containment: a failed or timed-out session leaves the note in
whatever state its completed edits produced — that partial state is
simply the new on-disk truth, and the next incorporation round starts
from a fresh read. Journal decoration is fail-open; nothing here may
block a publish.

Guru codes:
- #AG.00000003.EDITFAIL: incorporation session failed or timed out
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from gaius.core.budgets import INCORPORATION_NET_S

logger = logging.getLogger(__name__)

# Generous outer net only (progress doctrine): the agent loop is
# supervised by Engine/Complete's own token-progress machinery; this
# deadline exists for a dead facade, not a slow merge.


async def incorporate_into_note(
    note_path: Path,
    task: str,
    timeout_s: float = INCORPORATION_NET_S,
) -> bool:
    """Run one multi-turn incorporation session against a note.

    Returns True when the note's bytes changed. Never raises.
    """
    try:
        before = note_path.read_text(encoding="utf-8")
    except OSError as e:
        logger.warning(f"#AG.00000003.EDITFAIL note unreadable: {e}")
        return False

    prompt = f"""You are performing a multi-turn INCORPORATION edit on one Agenda note.

NOTE FILE (absolute path): {note_path}

Protocol (strict):
1. READ the note file with your read tool first — never assume its
   content from this prompt.
2. You MUST modify the file with your edit tool: exact oldText ->
   newText spans. Replying with proposed text WITHOUT editing the file
   is a FAILURE — the file on disk is the deliverable.
3. You are INCORPORATING new information into what is already there —
   preserve the existing content's substance; condense rather than
   delete when space demands it. Work in SEVERAL SMALL edits, each
   with a short unique oldText span (a sentence or two, never a whole
   paragraph block) — many small edits across turns beat one giant
   span.
4. If an edit fails to match, re-read the file and retry with a longer
   unique span.
5. Touch no other file. Do not use the terminal.
6. Finish by re-reading the file to confirm your edits landed, then
   reply with a one-line summary of what changed.

TASK:
{task}
"""
    try:
        from gaius.acp import ACPConfig, GaiusACPClient

        async with GaiusACPClient(
            ACPConfig(
                agent="thinking",
                auto_approve_fs=True,
                auto_approve_terminal=False,  # editor, not operator
                include_gaius_mcp=False,
                working_directory=str(note_path.parent),
            )
        ) as client:
            await asyncio.wait_for(
                client.prompt(message=prompt), timeout=timeout_s
            )
    except Exception as e:  # noqa: BLE001 — journal decoration is fail-open
        logger.warning(
            f"#AG.00000003.EDITFAIL incorporation session failed: {e}"
        )

    try:
        after = note_path.read_text(encoding="utf-8")
    except OSError:
        return False
    changed = after != before
    logger.info(
        "agenda incorporation %s: %s (%d -> %d bytes)",
        "applied" if changed else "left note unchanged",
        note_path.name,
        len(before),
        len(after),
    )
    return changed
