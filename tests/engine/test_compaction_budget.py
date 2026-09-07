"""Buffer compaction asks thinking for a bounded generation (COMPACTION_MAX_TOKENS)."""
from __future__ import annotations

import asyncio

from gaius.core import budgets
from gaius.flows import thinking_router as tr


def test_summarize_with_thinking_caps_the_generation(monkeypatch):
    seen: dict = {}

    async def fake_complete(self, *, prompt, max_tokens=None, **kw):
        seen["max_tokens"] = max_tokens
        return tr.RouterResponse(content="state", reasoning_content="r", model="m", input_tokens=1, output_tokens=1)

    monkeypatch.setattr(tr.LatticeRouter, "complete", fake_complete)
    monkeypatch.setattr(
        "gaius.engine.services.cognition_buffer.thinking_output_tokens", lambda prompt: 150_000
    )
    out = asyncio.run(tr.summarize_with_thinking("x" * 1000))
    assert out == "state"
    assert seen["max_tokens"] == budgets.COMPACTION_MAX_TOKENS == 65536


def test_small_prompt_room_wins_over_the_cap(monkeypatch):
    seen: dict = {}

    async def fake_complete(self, *, prompt, max_tokens=None, **kw):
        seen["max_tokens"] = max_tokens
        return tr.RouterResponse(content="state", reasoning_content="", model="m", input_tokens=1, output_tokens=1)

    monkeypatch.setattr(tr.LatticeRouter, "complete", fake_complete)
    monkeypatch.setattr(
        "gaius.engine.services.cognition_buffer.thinking_output_tokens", lambda prompt: 20_000
    )
    asyncio.run(tr.summarize_with_thinking("x"))
    assert seen["max_tokens"] == 20_000  # never ask for more than the context leaves
