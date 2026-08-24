"""Pi-style cut / serialize — no LLM."""

from gaius.engine.services.ambient_buffer import BufferEntry, BufferRole
from gaius.engine.services.buffer_compaction import (
    estimate_tokens,
    find_cut_index,
    plan_compaction,
    serialize_entries,
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


def test_serialize_truncates() -> None:
    e = BufferEntry.create(BufferRole.CONTENT, "x" * 5000, source_url="http://n")
    blob = serialize_entries([e])
    assert len(blob) < 2500
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
        buf = AmbientBuffer(max_bytes=8000)
        for i in range(12):
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
