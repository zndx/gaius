"""FmpMarketBufferFlow — market-wide FMP streams → prospects buffer → compaction.

(2026-09-04) Replaces ProspectsService._roll_fmp_buffer, the engine's 60 s
in-process loop that pulled seven FMP streams into a RAM FIFO and compacted
it through thinking. The FIFO is durable now (buffer_entries, buffer
'prospects'); the engine's ProspectsService reads through.

Steps map to ``machines { id: "fmp_roll" }`` in config/supervision/gaius.textproto:
ingest (start, ingest) → compact (compact, end). Kind ``fmp-roll`` →
RATE_METERED (0 GPU tokens; FMP is the metered resource, thinking is reached
through Engine/Complete on its own standing claim).
"""

from __future__ import annotations

import asyncio
from typing import Any

from metaflow import step

from gaius.agents.metaagent.telemetry import TracedFlow, traced_step
from gaius.flows import register_flow
from gaius.flows.base import GaiusFlow

WRITER = "flow:FmpMarketBufferFlow"
PROSPECTS_BUFFER_MAX_BYTES = 256 * 1024
GURU_FMPEMPTY = "#PS.00000007.FMPEMPTY"
GURU_FMPFAIL = "#PS.00000003.FMPFAIL"


async def _pool():
    import asyncpg

    from gaius.core.config import get_database_url

    return await asyncpg.create_pool(get_database_url(), min_size=1, max_size=3)


def _dedupe(entries: list, seen: set[str]) -> list:
    import hashlib

    fresh = []
    for e in entries:
        fp = hashlib.md5(e.content.encode("utf-8")).hexdigest()
        if fp in seen:
            continue
        seen.add(fp)
        fresh.append(e)
    return fresh


@register_flow("fmp-roll")
class FmpMarketBufferFlow(TracedFlow, GaiusFlow):
    """One roll of the prospects FIFO as a flow."""

    @traced_step
    @step
    def start(self):
        from gaius.flows.config import apply_metaflow_config
        from gaius.flows.lattice import require_signals_metaflow
        from gaius.flows.prospects.flow import load_watchlist

        apply_metaflow_config()
        require_signals_metaflow()
        self.watch = sorted(
            {str(w.get("symbol") or "").upper() for w in load_watchlist() if w.get("symbol")}
        )
        print(f"FMP roll: watchlist={len(self.watch)} symbols; thinking via Engine/Complete")
        self.next(self.ingest)

    @traced_step
    @step
    def ingest(self):
        """Seven market-wide FMP streams appended (dedupe by content)."""
        from gaius.engine.services import buffer_store
        from gaius.flows.prospects.market_feed import fetch_market_entries

        async def _go() -> dict[str, Any]:
            entries, errors = await fetch_market_entries(set(self.watch))
            if errors:
                print(f"{GURU_FMPFAIL} stream errors: {'; '.join(errors[:6])}")
            if not entries:
                raise RuntimeError(
                    f"{GURU_FMPEMPTY} FMP streams returned 0 rows "
                    f"(errors={len(errors)}). Try: /prospects status"
                )
            pool = await _pool()
            try:
                seen = await buffer_store.live_fingerprints(pool, "prospects")
                fresh = _dedupe(entries, seen)
                n = await buffer_store.append_many(pool, "prospects", fresh, writer=WRITER)
                stats = await buffer_store.live_stats(pool, "prospects")
            finally:
                await pool.close()
            return {
                "fetched": len(entries),
                "appended": n,
                "stream_errors": errors,
                "live_bytes": stats["bytes"],
                "live_entries": stats["count"],
            }

        self.ingest_result = asyncio.run(_go())
        print(f"ingest: {self.ingest_result}")
        self.next(self.compact)

    @traced_step
    @step
    def compact(self):
        """Compact through thinking when over the 90% target (thinking down = error)."""
        from gaius.engine.services import buffer_store
        from gaius.flows.thinking_router import summarize_with_thinking

        async def _go() -> dict[str, Any]:
            pool = await _pool()
            try:
                return await buffer_store.compact(
                    pool,
                    "prospects",
                    max_bytes=PROSPECTS_BUFFER_MAX_BYTES,
                    summarize=summarize_with_thinking,
                    writer=WRITER,
                )
            finally:
                await pool.close()

        self.compact_result = asyncio.run(_go())
        print(f"compact: {self.compact_result}")
        self.next(self.end)

    @traced_step
    @step
    def end(self):
        self.result = {"ingest": self.ingest_result, "compact": self.compact_result}
        print(f"FmpMarketBufferFlow done: {self.result}")


if __name__ == "__main__":
    from gaius.flows.config import apply_metaflow_config

    apply_metaflow_config()
    FmpMarketBufferFlow()
