"""AmbientSynthesisFlow — HN + publishing refresh → compaction → cognition synthesis.

(2026-09-04) Replaces AmbientWorkloadService's continuous in-engine cycle
(``_run_varied_cycle``: fetch, compact, synthesize, plus a synthetic
reasoning workload that evicted and restored endpoints). The synthetic
eviction dance is dropped on purpose — declared resource intents are how
GPU contention is resolved now. The Bytez buffer analysis and Brave
proposal steps of the old cycle are not carried over (external backends
outside the thinking lane; a follow-up if their product is wanted).

Steps map to ``machines { id: "ambient_synthesis" }`` in
config/supervision/gaius.textproto: fetch (start, fetch) → compact →
synthesize (synthesize, end). The synthesize phase declares the shared
embedding intent (light 1/1 @40): Aperture admission is ColBERT MaxSim.

Engine-First: thinking is reached through zndx.engine.v1.Engine/Complete
(``gaius.flows.thinking_router``); the durable buffers are written through
``gaius.engine.services.buffer_store``. Kind ``ambient-synthesis`` → COMPUTE
(0 tokens of its own).
"""

from __future__ import annotations

import asyncio
import os
from types import SimpleNamespace
from typing import Any

from metaflow import Parameter, step

from gaius.agents.metaagent.telemetry import TracedFlow, traced_step
from gaius.flows import register_flow
from gaius.flows.base import GaiusFlow

WRITER = "flow:AmbientSynthesisFlow"
GURU_HN = "#AMB.00000003.HNFETCH"
GURU_SYNTH = "#AMB.00000004.SYNTHFAIL"


def _ambient_cfg() -> Any:
    """Buffer sizing/source from the engine's config dataclass defaults, with the
    same env overrides the engine honours."""
    from gaius.engine.config import AmbientBufferConfig

    cfg = AmbientBufferConfig()
    src = (os.environ.get("GAIUS_AMBIENT_SOURCE_URL") or "").strip()
    if src:
        cfg.source_url = src
    return cfg


async def fetch_hn_entries(cfg: Any) -> list:
    """Hacker News stories/comments → CONTENT entries (port of _fetch_content)."""
    import httpx

    from gaius.engine.services.ambient_buffer import BufferEntry, BufferRole
    from gaius.workers.config import WorkerConfig
    from gaius.workers.fetchers.hackernews import HNFetcher
    from gaius.workers.models import FeedSource, SourceType

    source = FeedSource(
        id=0,
        name="ambient-hn",
        source_type=SourceType.HACKERNEWS,
        base_url=cfg.source_url,
        config={
            "firebase_stories": True,
            "newcomments": False,
            "max_items": max(int(cfg.max_items), 15),
            "buffer_only": True,
        },
    )
    async with httpx.AsyncClient(timeout=30.0) as http_client:
        fetcher = HNFetcher(WorkerConfig(), http_client)
        result = await asyncio.wait_for(fetcher.fetch(source), timeout=120)
    if result.error:
        raise RuntimeError(f"{GURU_HN} HN fetch failed: {result.error}")
    out: list = []
    from datetime import datetime

    for item in result.items:
        content = item.content or item.summary or item.title
        if not content:
            continue
        item_meta = item.metadata or {}
        meta: dict[str, Any] = {
            "title": item.title,
            "hn_id": item_meta.get("hn_id"),
            "is_comment": item_meta.get("is_comment", False),
            "fetched_at": datetime.now().isoformat(),
        }
        if item_meta.get("author"):
            meta["author"] = item_meta["author"]
        elif item.authors:
            meta["author"] = item.authors[0]
        if item_meta.get("story_title"):
            meta["story_title"] = item_meta["story_title"]
        if item_meta.get("story_id"):
            meta["story_id"] = item_meta["story_id"]
        out.append(
            BufferEntry.create(
                role=BufferRole.CONTENT,
                content=content,
                source_url=item.url or "",
                metadata=meta,
            )
        )
    return out


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


@register_flow("ambient-synthesis")
class AmbientSynthesisFlow(TracedFlow, GaiusFlow):
    """One ambient cycle as a flow: refresh the ambient + publishing buffers,
    compact them through thinking, run the cognition synthesis."""

    skip_synthesis = Parameter(
        "skip_synthesis",
        help="Refresh and compact only (no cognition synthesis episode)",
        default=False,
        type=bool,
    )

    @traced_step
    @step
    def start(self):
        from gaius.flows.config import apply_metaflow_config
        from gaius.flows.lattice import require_signals_metaflow

        apply_metaflow_config()
        require_signals_metaflow()
        cfg = _ambient_cfg()
        self.buffer_max_bytes = int(cfg.buffer_max_bytes)
        self.hn_source = cfg.source_url
        print(f"Ambient synthesis: hn={self.hn_source} buffer_max={self.buffer_max_bytes}")
        print("LLM: local thinking via zndx.engine.v1.Engine/Complete (Signals Metaflow)")
        self.next(self.fetch)

    @traced_step
    @step
    def fetch(self):
        """HN + publishing rows appended to the durable buffers (dedupe by content)."""
        from gaius.engine.services import buffer_store
        from gaius.engine.services.publishing_axis import (
            load_publishing_items,
            publishing_entries,
        )

        cfg = _ambient_cfg()

        async def _go() -> dict[str, int]:
            pool = await _pool()
            try:
                hn = await fetch_hn_entries(cfg)
                seen = await buffer_store.live_fingerprints(pool, "ambient")
                hn_new = _dedupe(hn, seen)
                n_hn = await buffer_store.append_many(pool, "ambient", hn_new, writer=WRITER)
                async with pool.acquire() as conn:
                    rows = await load_publishing_items(conn)
                pub = publishing_entries(rows)
                seen_p = await buffer_store.live_fingerprints(pool, "publishing")
                pub_new = _dedupe(pub, seen_p)
                n_pub = await buffer_store.append_many(pool, "publishing", pub_new, writer=WRITER)
                return {
                    "hn_fetched": len(hn),
                    "hn_appended": n_hn,
                    "publishing_seen": len(pub),
                    "publishing_appended": n_pub,
                }
            finally:
                await pool.close()

        self.fetch_result = asyncio.run(_go())
        print(f"fetch: {self.fetch_result}")
        self.next(self.compact)

    @traced_step
    @step
    def compact(self):
        """Ambient + publishing FIFOs compacted through thinking when over target."""
        from gaius.engine.services import buffer_store
        from gaius.flows.thinking_router import summarize_with_thinking

        async def _go() -> dict[str, Any]:
            pool = await _pool()
            try:
                out: dict[str, Any] = {}
                for name in ("ambient", "publishing"):
                    out[name] = await buffer_store.compact(
                        pool,
                        name,
                        max_bytes=self.buffer_max_bytes,
                        summarize=summarize_with_thinking,
                        writer=WRITER,
                    )
                return out
            finally:
                await pool.close()

        self.compact_result = asyncio.run(_go())
        for name, r in self.compact_result.items():
            print(f"compact {name}: {r}")
        self.next(self.synthesize)

    @traced_step
    @step
    def synthesize(self):
        """Cognition synthesis: three axes → thinking → cognition_buffer + agenda."""
        if self.skip_synthesis:
            self.synthesis_result = {"skipped": True}
            print("synthesize: skipped (--skip_synthesis)")
            self.next(self.end)
            return

        from gaius.engine.services.buffer_store import DurableBuffer
        from gaius.engine.services.cognition_synthesis import run_synthesis_cycle
        from gaius.flows.thinking_router import LatticeRouter

        async def _go() -> dict[str, Any]:
            pool = await _pool()
            try:
                ambient = DurableBuffer(pool, "ambient", self.buffer_max_bytes)
                prospects = DurableBuffer(pool, "prospects", 256 * 1024)
                publishing = DurableBuffer(pool, "publishing", 256 * 1024)
                for b in (ambient, prospects, publishing):
                    await b.refresh(force=True)
                return await run_synthesis_cycle(
                    backend_router=LatticeRouter(),
                    db_pool=pool,
                    ambient_buffer=ambient,
                    prospects_service=SimpleNamespace(_buffer=prospects),
                    publishing_buffer=publishing,
                )
            finally:
                await pool.close()

        try:
            self.synthesis_result = asyncio.run(_go())
        except Exception as e:  # noqa: BLE001 — re-raised with the guru code
            raise RuntimeError(f"{GURU_SYNTH} cognition synthesis failed: {e}") from e
        print(f"synthesize: {self.synthesis_result}")
        self.next(self.end)

    @traced_step
    @step
    def end(self):
        self.result = {
            "fetch": self.fetch_result,
            "compact": {k: {kk: v[kk] for kk in ("skipped", "dropped_ids", "created", "live_bytes") if kk in v}
                        for k, v in self.compact_result.items()},
            "synthesis": self.synthesis_result,
        }
        print(f"AmbientSynthesisFlow done: {self.result}")


if __name__ == "__main__":
    from gaius.flows.config import apply_metaflow_config

    apply_metaflow_config()
    AmbientSynthesisFlow()
