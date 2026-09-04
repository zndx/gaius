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
    """Compaction summarizer: content, else the reasoning trace; empty is an error."""
    resp = await LatticeRouter().complete(prompt=prompt, temperature=0.2, task_type="buffer_compaction")
    text = (resp.content or resp.reasoning_content or "").strip()
    if not text:
        raise RuntimeError("empty thinking compaction")
    return text
