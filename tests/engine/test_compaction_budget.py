"""Compaction uses xhigh thinking; ceiling is the leftover window, not 65k."""
from __future__ import annotations

import asyncio

from gaius.core import budgets
from gaius.flows import thinking_router as tr


def test_compaction_ceiling_is_the_scratch_leftover_not_65k():
    assert budgets.COMPACTION_MAX_TOKENS == 196_608
    assert budgets.COMPACTION_MAX_TOKENS == budgets.THINKING_CONTEXT_WINDOW - 65_536
    assert budgets.COMPACTION_GENERATION_RESERVE_TOKENS == 131_072
    assert budgets.COMPACTION_GENERATION_RESERVE_TOKENS > 65_536


def test_summarize_with_thinking_uses_xhigh_and_does_not_clip_150k(monkeypatch):
    seen: dict = {}

    async def fake_complete(self, *, prompt, max_tokens=None, **kw):
        seen["max_tokens"] = max_tokens
        seen["agent_alias"] = kw.get("agent_alias")
        return tr.RouterResponse(
            content="state", reasoning_content="r" * 8000, model="m",
            input_tokens=1, output_tokens=1,
        )

    monkeypatch.setattr(tr.LatticeRouter, "complete", fake_complete)
    monkeypatch.setattr(
        "gaius.engine.services.cognition_buffer.thinking_output_tokens", lambda prompt: 150_000
    )
    out = asyncio.run(tr.summarize_with_thinking("x" * 1000))
    assert out == "state"
    assert seen["max_tokens"] == 150_000
    assert seen["max_tokens"] < budgets.COMPACTION_MAX_TOKENS
    assert seen["agent_alias"] == "thinking"


def test_summarize_returns_the_briefing_not_the_trace(monkeypatch):
    async def fake_complete(self, *, prompt, max_tokens=None, **kw):
        return tr.RouterResponse(
            content="## Goal\nbrief",
            reasoning_content="long xhigh trace that must not be stored",
            model="m",
            input_tokens=1,
            output_tokens=90_000,
        )

    monkeypatch.setattr(tr.LatticeRouter, "complete", fake_complete)
    monkeypatch.setattr(
        "gaius.engine.services.cognition_buffer.thinking_output_tokens", lambda prompt: 150_000
    )
    assert asyncio.run(tr.summarize_with_thinking("p")) == "## Goal\nbrief"


def test_scratch_cap_still_bounds_a_huge_leftover(monkeypatch):
    seen: dict = {}

    async def fake_complete(self, *, prompt, max_tokens=None, **kw):
        seen["max_tokens"] = max_tokens
        return tr.RouterResponse(content="state", reasoning_content="", model="m", input_tokens=1, output_tokens=1)

    monkeypatch.setattr(tr.LatticeRouter, "complete", fake_complete)
    monkeypatch.setattr(
        "gaius.engine.services.cognition_buffer.thinking_output_tokens", lambda prompt: 250_000
    )
    asyncio.run(tr.summarize_with_thinking("x"))
    assert seen["max_tokens"] == budgets.COMPACTION_MAX_TOKENS


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
