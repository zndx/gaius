"""Pi-style cut / serialize — no LLM."""

import pytest

from gaius.engine.services.ambient_buffer import BufferEntry, BufferRole
from gaius.engine.services.buffer_compaction import (
    estimate_tokens,
    find_cut_index,
    plan_compaction,
    serialize_entries,
)


class _CharTok:
    def encode(self, text: str, add_special_tokens: bool = False) -> list[str]:
        return list(text or "")

    def decode(self, ids: list[str], skip_special_tokens: bool = True) -> str:
        return "".join(ids)


@pytest.fixture(autouse=True)
def _fake_thinking_tokenizer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "gaius.engine.services.cognition_buffer.thinking_tokenizer",
        lambda: _CharTok(),
    )


def test_find_cut_keeps_recent_window() -> None:
    counts = [1000] * 50
    cut = find_cut_index(counts, keep_recent_tokens=5000)
    kept = sum(counts[cut:])
    assert kept >= 5000
    assert cut > 0


def test_find_cut_keeps_huge_last_entry() -> None:
    counts = [10, 10, 50_000]
    assert find_cut_index(counts, keep_recent_tokens=20_000) == 2


def test_serialize_keeps_full_entry() -> None:
    e = BufferEntry.create(BufferRole.CONTENT, "x" * 5000, source_url="http://n")
    blob = serialize_entries([e])
    assert "x" * 5000 in blob
    assert "[content]" in blob


def test_plan_compaction_cut_at_entry_boundary() -> None:
    entries = [
        BufferEntry.create(BufferRole.CONTENT, "old " * 8000),
        BufferEntry.create(BufferRole.CONTENT, "mid " * 8000),
        BufferEntry.create(BufferRole.CONTENT, "new " * 100),
    ]
    plan = plan_compaction(entries, keep_recent_tokens=200)
    assert plan is not None
    assert plan.cut_index >= 1
    assert plan.first_kept_id == entries[plan.cut_index].id
    assert "old" in plan.material or "mid" in plan.material


def test_estimate_tokens_nonzero() -> None:
    assert estimate_tokens("abcd") >= 1


def test_compact_if_needed_replaces_prefix_with_summary() -> None:
    import asyncio

    from gaius.engine.services.ambient_buffer import AmbientBuffer

    async def _run() -> None:
        buf = AmbientBuffer(max_bytes=50_000)
        for i in range(16):
            await buf.add_entry(
                BufferEntry.create(BufferRole.CONTENT, f"story-{i} " * 400)
            )
        before = buf.get_stats()["entry_count"]

        async def fake(prompt: str) -> str:
            assert "## Goal" in prompt
            assert "story-" in prompt
            return "## Goal\nHN front page\n## Next Steps\nBrave the makers story"

        out = await buf.compact_if_needed(fake)
        assert out.get("success") is True
        assert buf.get_stats()["entry_count"] < before
        summaries = await buf.get_entries_by_role(BufferRole.SUMMARY)
        assert any(s.metadata.get("kind") == "compaction" for s in summaries)

    asyncio.run(_run())


def test_compact_if_needed_refuses_a_summary_larger_than_a_quarter_of_the_window() -> None:
    """2026-09-06: a 159 946-byte reasoning trace was accepted as the SUMMARY of a
    79 KB window and poisoned every later compaction. A summary is bounded."""
    import asyncio

    from gaius.engine.services.ambient_buffer import AmbientBuffer

    async def _run() -> None:
        buf = AmbientBuffer(max_bytes=50_000)
        for i in range(16):
            await buf.add_entry(BufferEntry.create(BufferRole.CONTENT, f"story-{i} " * 400))
        before = buf.get_stats()["entry_count"]

        async def bloated(prompt: str) -> str:
            return "## Goal\n" + ("reasoning " * 3000)  # ~30 KB > 50 KB / 4

        with pytest.raises(RuntimeError) as ei:
            await buf.compact_if_needed(bloated)
        assert "#BUF.00000002.SUMMARYBLOAT" in str(ei.value)
        # nothing written, window intact
        assert buf.get_stats()["entry_count"] == before
        assert not await buf.get_entries_by_role(BufferRole.SUMMARY)

    asyncio.run(_run())
