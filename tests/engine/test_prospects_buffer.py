"""prospects-buffer is a separate FIFO with the Ambient byte contract."""

from __future__ import annotations

import asyncio

from gaius.engine.services.prospects_buffer import (
    ProspectsBuffer,
    ProspectsRole,
    entry,
)


def test_fifo_evicts_oldest() -> None:
    async def _run() -> None:
        buf = ProspectsBuffer(max_bytes=200)
        await buf.add_entry(entry(ProspectsRole.FILING, "a" * 80, symbol="AAA"))
        await buf.add_entry(entry(ProspectsRole.FILING, "b" * 80, symbol="BBB"))
        await buf.add_entry(entry(ProspectsRole.COMPACT, "c" * 80, symbol="CCC"))
        stats = buf.get_stats()
        assert stats["current_bytes"] <= 200
        assert stats["entry_count"] >= 1
        assert stats["eviction_count"] >= 1

    asyncio.run(_run())
