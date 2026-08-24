"""Thinking Completes are sized with the Qwen3.8-27B tokenizer."""

from __future__ import annotations

import pytest

from gaius.engine.services.cognition_buffer import (
    DEFAULT_SCRATCH_TOKEN_BUDGET,
    NEXT_QUESTION_RESERVE_TOKENS,
    clip_to_token_budget,
    pack_thinking_slices,
    thinking_output_tokens,
    thinking_read_timeout_s,
    thinking_token_count,
)


class _CharTok:
    """1 token per character — proves we are not using chars/3 or chars/4."""

    def encode(self, text: str, add_special_tokens: bool = False) -> list[str]:
        return list(text or "")

    def decode(self, ids: list[str], skip_special_tokens: bool = True) -> str:
        return "".join(ids)


@pytest.fixture
def char_tok(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "gaius.engine.services.cognition_buffer.thinking_tokenizer",
        lambda: _CharTok(),
    )


def test_output_tokens_are_scratch_minus_prompt(char_tok: None) -> None:
    prompt = "abcd"
    assert thinking_token_count(prompt) == 4
    assert thinking_output_tokens(prompt) == DEFAULT_SCRATCH_TOKEN_BUDGET - 4


def test_clip_uses_tokenizer_ids_not_char_heuristic(char_tok: None) -> None:
    assert clip_to_token_budget("abcdefghij", 4) == "abcd"


def test_pack_leaves_full_think_budget(char_tok: None) -> None:
    tmpl = "HEAD{slices}TAIL"
    huge = "x" * (DEFAULT_SCRATCH_TOKEN_BUDGET * 2)
    packed = pack_thinking_slices(tmpl, huge)
    # leftover generation ≥ next-question reserve
    assert thinking_output_tokens(packed) >= NEXT_QUESTION_RESERVE_TOKENS


def test_read_timeout_scales_with_output_budget() -> None:
    assert thinking_read_timeout_s(8_000) >= 420
    assert thinking_read_timeout_s(65_536) > thinking_read_timeout_s(3_072)


def test_qwen_tokenizer_counts_real_tokens() -> None:
    from gaius.engine.services.cognition_buffer import thinking_tokenizer

    tok = thinking_tokenizer()
    ids = tok.encode("Week 34 opened with federation architecture.", add_special_tokens=False)
    assert 5 <= len(ids) <= 20
    n = thinking_token_count("a")
    assert n >= 1
    # not the old chars/3 heuristic
    assert thinking_token_count("abcdef") != 2
