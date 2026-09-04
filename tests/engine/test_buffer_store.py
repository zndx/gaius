"""Durable buffer store: pure diff, RAM fallback, hydration contract."""

from __future__ import annotations

import asyncio

from gaius.engine.services.ambient_buffer import AmbientBuffer, BufferEntry, BufferRole
from gaius.engine.services.buffer_store import DurableBuffer, diff_compaction


def _e(text: str) -> BufferEntry:
    return BufferEntry.create(role=BufferRole.CONTENT, content=text)


def test_diff_compaction_names_dropped_and_created() -> None:
    a, b, c = _e("a"), _e("b"), _e("c")
    summary = BufferEntry.create(role=BufferRole.SUMMARY, content="a+b")
    dropped, created = diff_compaction([a, b, c], [summary, c])
    assert dropped == [a.id, b.id]
    assert created == [summary]


def test_load_replaces_fifo_and_bytes() -> None:
    buf = AmbientBuffer(max_bytes=1024)
    entries = [_e("hello"), _e("world!")]
    buf.load(entries)
    assert buf.entry_count == 2
    assert buf.current_bytes == sum(e.content_bytes for e in entries)


def test_durable_buffer_without_pool_is_ram() -> None:
    buf = DurableBuffer(None, "ambient", 1024)
    assert buf.durable is False

    async def _go() -> None:
        await buf.add_entry(_e("x"))
        snap = await buf.snapshot()
        assert [e.content for e in snap] == ["x"]
        out = await buf.compact_if_needed(lambda p: asyncio.sleep(0, result="never"))
        assert out.get("skipped") is True

    asyncio.run(_go())


def test_durable_buffer_hydrates_from_pool() -> None:
    """snapshot() reads through: the table is the truth, RAM is the cache."""
    rows = [
        {
            "id": _e("r1").id,
            "role": "content",
            "content": "r1",
            "content_bytes": 2,
            "source_url": "",
            "metadata": "{}",
            "created_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc),
        }
    ]

    class _Conn:
        async def fetch(self, _sql, _buffer):
            return rows

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    class _Pool:
        def acquire(self):
            return _Conn()

    buf = DurableBuffer(_Pool(), "ambient", 1024)

    async def _go() -> None:
        snap = await buf.snapshot()
        assert [e.content for e in snap] == ["r1"]
        assert buf.current_bytes == 2
        assert buf.get_stats()["entry_count"] == 1

    asyncio.run(_go())
