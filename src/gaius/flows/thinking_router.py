"""Thinking-lane access for flows: the engine's ``backend_router.complete``
contract over ``zndx.engine.v1.Engine/Complete`` (Engine-First: never a
model URL, never optillm directly).

Two shapes the migrated loops need:

* ``LatticeRouter`` — quacks like the engine's BackendRouter for
  ``cognition_synthesis.run_synthesis_cycle`` (``.content``,
  ``.reasoning_content``, ``.error``, ``.model``, ``.input_tokens``,
  ``.output_tokens``).
* ``summarize_with_thinking`` — the ``summarize(prompt) -> str`` callback
  AmbientBuffer's compaction takes.

Budgets and read deadlines derive from ``gaius.engine.services.cognition_buffer``
(``thinking_output_tokens`` / ``thinking_read_timeout_s``), never literals.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any


@dataclass
class RouterResponse:
    content: str
    reasoning_content: str
    model: str
    input_tokens: int
    output_tokens: int
    error: str | None = None


class LatticeRouter:
    """BackendRouter façade for flow processes."""

    async def complete(
        self,
        *,
        prompt: str,
        agent_alias: str = "thinking",
        max_tokens: int | None = None,
        temperature: float = 0.2,
        task_type: str = "",
        enable_thinking: bool = True,
        preserve_thinking: bool = False,
        **_ignored: Any,
    ) -> RouterResponse:
        from gaius.engine.services.cognition_buffer import (
            thinking_output_tokens,
            thinking_read_timeout_s,
        )
        from gaius.flows.lattice import complete

        if agent_alias not in ("thinking", "reasoning"):
            raise ValueError(
                f"LatticeRouter serves the thinking lane only (got agent_alias={agent_alias!r})"
            )
        max_tok = int(max_tokens or thinking_output_tokens(prompt))
        r = await asyncio.to_thread(
            complete,
            prompt,
            max_tokens=max_tok,
            temperature=float(temperature),
            timeout_s=thinking_read_timeout_s(max_tok),
        )
        return RouterResponse(
            content=r.text or "",
            reasoning_content=r.reasoning_content or "",
            model=r.model or "thinking",
            input_tokens=int(r.prompt_tokens or 0),
            output_tokens=int(r.completion_tokens or 0),
        )


async def summarize_with_thinking(prompt: str) -> str:
    """Compaction summarizer: the model's ANSWER only; empty is an error.

    The reasoning trace is never a summary. Until 2026-09-05 the stream
    assembler dropped every trace, so a `content or reasoning_content`
    fallback was inert; the moment traces became visible, a think-to-EOS
    compaction (content 0, reasoning 159 890 chars) was written into the
    ambient buffer as a 160 KB SUMMARY row, every later compaction re-read
    it, reasoned to the 89 702-token cap and failed, and the class was dark
    for 7 h (2026-09-06 01:13 → 08:47). Fail fast instead: the flow's
    #BUF.00000001.COMPACTFAIL names the class, the window stays intact for
    the next attempt, nothing poisoned is written.
    """
    resp = await LatticeRouter().complete(prompt=prompt, temperature=0.2, task_type="buffer_compaction")
    text = (resp.content or "").strip()
    if not text:
        raise RuntimeError(
            "empty thinking compaction "
            f"(reasoning_chars={len(resp.reasoning_content or '')}, output_tokens={resp.output_tokens}): "
            "the model reasoned to the end without answering; the trace is not a summary"
        )
    return text
