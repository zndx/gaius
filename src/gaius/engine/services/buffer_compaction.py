"""Pi-style compaction for Ambient and Prospects FIFOs.

Naive FIFO drop is not summarization. Cut only at BufferEntry boundaries,
keep a recent token window, serialize the prefix, and replace it with a
structured summary from thinking. If thinking is down, fail visible —
do not pretend eviction is compaction.

Guru: #BUF.00000001.COMPACTFAIL
"""

from __future__ import annotations

from dataclasses import dataclass

from gaius.engine.services.cognition_buffer import (
    CHARS_PER_TOKEN,
    NEXT_QUESTION_RESERVE_TOKENS,
    THINKING_CONTEXT_TOKENS,
    thinking_token_count,
)

KEEP_RECENT_TOKENS = 20_000

GURU = (
    "Buffer compaction needs thinking.\n"
    "  Guru: #BUF.00000001.COMPACTFAIL\n"
    "  Try: /health fix endpoints\n"
    "  Or:  /gpu status thinking"
)

COMPACT_PROMPT = """You are a context summarization assistant, not a coding assistant.
Produce a shift-handoff briefing. Do not continue the conversation.

Sections (use these headings):
## Goal
## Constraints & Preferences
## Progress
### Done
### In Progress
### Blocked
## Key Decisions
## Next Steps
## Critical Context

Prior summary (refine iteratively; empty if none):
{prior}

Material to condense:
{material}
"""


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, thinking_token_count(text))


def find_cut_index(token_counts: list[int], keep_recent_tokens: int) -> int:
    """First index to keep. Walk backward; never split an entry.

    If one entry exceeds keep_recent, keep that whole entry (cut at i).
    """
    if not token_counts:
        return 0
    acc = 0
    for i in range(len(token_counts) - 1, -1, -1):
        t = token_counts[i]
        if acc > 0 and acc + t > keep_recent_tokens:
            return i + 1
        acc += t
    return 0


def serialize_entries(entries: list) -> str:
    """Plain text so the summarizer condenses content, not a chat."""
    blocks: list[str] = []
    for e in entries:
        role = getattr(getattr(e, "role", None), "value", None) or "content"
        url = getattr(e, "source_url", "") or ""
        body = getattr(e, "content", "") or ""
        head = f"[{role}]"
        if url:
            head += f" {url}"
        blocks.append(f"{head}\n{body}")
    return "\n\n".join(blocks)


def compaction_prompt(material: str, prior: str = "") -> str:
    from gaius.engine.services.cognition_buffer import pack_thinking_slices

    prior_s = prior or "(none)"
    tmpl = COMPACT_PROMPT.format(prior=prior_s, material="{slices}")
    return pack_thinking_slices(tmpl, material)


def over_token_budget(
    total_tokens: int,
    *,
    context_window: int = THINKING_CONTEXT_TOKENS,
    reserve_tokens: int = NEXT_QUESTION_RESERVE_TOKENS,
) -> bool:
    return total_tokens > context_window - reserve_tokens


@dataclass(frozen=True)
class CompactionPlan:
    cut_index: int
    first_kept_id: str
    material: str
    prior: str
    dropped: int


def plan_compaction(
    entries: list,
    *,
    keep_recent_tokens: int = KEEP_RECENT_TOKENS,
    keep_recent_bytes: int | None = None,
) -> CompactionPlan | None:
    if len(entries) < 2:
        return None
    if keep_recent_bytes is not None:
        counts = [int(getattr(e, "content_bytes", 0) or 0) for e in entries]
        cut = find_cut_index(counts, keep_recent_bytes)
    else:
        counts = [estimate_tokens(getattr(e, "content", "") or "") for e in entries]
        cut = find_cut_index(counts, keep_recent_tokens)
    if cut <= 0:
        return None
    prefix = entries[:cut]
    kept = entries[cut:]
    prior = ""
    for e in reversed(entries[:cut]):
        meta = getattr(e, "metadata", None) or {}
        if meta.get("kind") == "compaction":
            prior = e.content
            break
    first_kept = getattr(kept[0], "id", "") if kept else ""
    return CompactionPlan(
        cut_index=cut,
        first_kept_id=str(first_kept),
        material=serialize_entries(prefix),
        prior=prior,
        dropped=len(prefix),
    )
