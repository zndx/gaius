"""summarize_with_thinking returns the model's ANSWER only — never the trace.

2026-09-06: once reasoning traces became visible (vLLM `reasoning` delta fix),
the old `content or reasoning_content` fallback wrote a 160 KB think-to-EOS
trace into the ambient buffer as a SUMMARY row and the class was dark for 7 h.
"""

import asyncio

import pytest

from gaius.flows import thinking_router as tr


def _resp(content: str, reasoning: str, out_tokens: int = 10) -> tr.RouterResponse:
    return tr.RouterResponse(
        content=content, reasoning_content=reasoning, model="thinking",
        input_tokens=100, output_tokens=out_tokens,
    )


def test_trace_without_answer_is_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_complete(self, **kw):  # noqa: ANN001
        return _resp("", "thinking " * 20_000, out_tokens=89_702)

    monkeypatch.setattr(tr.LatticeRouter, "complete", fake_complete)
    with pytest.raises(RuntimeError) as ei:
        asyncio.run(tr.summarize_with_thinking("## Goal\ncompact"))
    msg = str(ei.value)
    assert "empty thinking compaction" in msg
    assert "reasoning_chars=" in msg and "output_tokens=89702" in msg


def test_answer_is_returned_stripped(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_complete(self, **kw):  # noqa: ANN001
        return _resp("  ## Goal\nsummary\n", "some trace")

    monkeypatch.setattr(tr.LatticeRouter, "complete", fake_complete)
    assert asyncio.run(tr.summarize_with_thinking("p")) == "## Goal\nsummary"
