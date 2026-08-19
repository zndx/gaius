"""CltSkosEvalFlow — admit Gaius inbound, extract CLT, ground spans.

P0: ingest → extract/ground. SKOS publish to sdg-corpora/contrib/ is P1.
ACP prefLabel mint is P2a. ACP alignment is P2b. SAE extract is P3.

    uv run python -m gaius.flows.clt_skos.flow run --limit 4
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from metaflow import Parameter, step

from gaius.flows import register_flow
from gaius.flows.base import GaiusFlow
from gaius.hx.lineage.events import Dataset


@register_flow("clt-skos-eval")
class CltSkosEvalFlow(GaiusFlow):
    """Evaluate CLT activations on MaxSim-admitted 512-token Gaius items."""

    limit = Parameter("limit", help="Max source documents", default=8, type=int)
    gpu_index = Parameter("gpu-index", help="CLT GPU", default=4, type=int)
    extract_top_k = Parameter("extract-top-k", help="Top-k per position", default=16, type=int)
    skip_extract = Parameter(
        "skip-extract",
        help="Admit only (no GPU extract)",
        default=False,
        type=bool,
    )

    @step
    def start(self):
        from gaius.engine.services.clt_skos_aperture import materialize_aperture
        from gaius.engine.services.sdg_aperture import SdgAperture

        self.aperture = SdgAperture.load()
        self.index = materialize_aperture(self.aperture)
        self.since_iso = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
        print(
            f"clt_skos.start strategy={self.aperture.strategy_id} "
            f"C={self.aperture.n} tau={self.aperture.tau} "
            f"grain={self.aperture.colbert_token_limit} "
            f"collection={self.aperture.collection} "
            f"index={self.index}"
        )
        self.emit_lineage_start(
            job_name="clt_skos_eval",
            inputs=[Dataset.from_source("postgres", "content_items")],
        )
        self.next(self.admit)

    @step
    def admit(self):
        from gaius.engine.services.clt_skos_admit import (
            admit_text,
            build_qdrant_maxsim,
            load_source_items,
        )
        from gaius.engine.services.clt_skos_aperture import v2_offsets
        from gaius.engine.services.clt_skos_ledger import (
            ensure_ledger,
            upsert_admitted,
        )
        from gaius.engine.services.sdg_aperture import SdgAperture
        from gaius.storage.database import get_database_url
        import asyncpg

        aperture = SdgAperture.load()
        maxsim = build_qdrant_maxsim(aperture)

        async def _run() -> dict:
            pool = await asyncpg.create_pool(get_database_url())
            try:
                await ensure_ledger(pool)
                since = datetime.fromisoformat(self.since_iso)
                items = await load_source_items(
                    pool, since=since, limit=int(self.limit)
                )
                kept = 0
                ids: list[int] = []
                for row in items:
                    windows = admit_text(
                        row["text"] or "",
                        aperture=aperture,
                        maxsim=maxsim,
                        require_maxsim=True,
                        encode_offsets=v2_offsets,
                    )
                    for w in windows:
                        item_id = await upsert_admitted(
                            pool,
                            source_id=str(row["source_id"]),
                            char_start=w.start,
                            char_end=w.end,
                            text=w.text,
                            aperture_code=w.code,
                            margin=w.margin,
                        )
                        ids.append(item_id)
                        kept += 1
                return {"sources": len(items), "admitted": kept, "item_ids": ids}
            finally:
                await pool.close()

        self.admit_stats = asyncio.run(_run())
        print(
            f"clt_skos.admit sources={self.admit_stats['sources']} "
            f"windows={self.admit_stats['admitted']}"
        )
        self.next(self.extract)

    @step
    def extract(self):
        from gaius.engine.services.clt_skos_extract import extract_positional
        from gaius.engine.services.clt_skos_ground import spans_for_features
        from gaius.engine.services.clt_skos_ledger import insert_activations
        from gaius.storage.database import get_database_url
        import asyncpg

        item_ids: list[int] = list(self.admit_stats.get("item_ids") or [])
        if self.skip_extract or not item_ids:
            self.extract_stats = {"items": 0, "rows": 0, "skipped": True}
            self.next(self.end)
            return

        async def _run() -> dict:
            pool = await asyncpg.create_pool(get_database_url())
            rows_n = 0
            try:
                async with pool.acquire() as conn:
                    items = await conn.fetch(
                        "SELECT id, text FROM admitted_item WHERE id = ANY($1::bigint[])",
                        item_ids,
                    )
                for row in items:
                    got = extract_positional(
                        row["text"],
                        gpu_index=int(self.gpu_index),
                        top_k=int(self.extract_top_k),
                    )
                    grounded = spans_for_features(got["features"], got["offsets"])
                    rows_n += await insert_activations(pool, int(row["id"]), grounded)
                return {"items": len(items), "rows": rows_n, "skipped": False}
            finally:
                await pool.close()

        self.extract_stats = asyncio.run(_run())
        print(
            f"clt_skos.extract items={self.extract_stats['items']} "
            f"rows={self.extract_stats['rows']}"
        )
        self.next(self.propose)

    @step
    def propose(self):
        from gaius.engine.services.clt_skos_propose import (
            observed_features,
            write_candidate_ttl,
        )
        from gaius.storage.database import get_database_url
        import asyncpg

        async def _run() -> dict:
            pool = await asyncpg.create_pool(get_database_url())
            try:
                feats = await observed_features(pool, min_items=2)
                if len(feats) < 8:
                    feats = await observed_features(pool, min_items=1)
                path = write_candidate_ttl(feats[:120])
                return {"concepts": min(120, len(feats)), "path": str(path)}
            finally:
                await pool.close()

        self.propose_stats = asyncio.run(_run())
        print(f"clt_skos.propose {self.propose_stats}")
        self.next(self.acp_label)

    @step
    def acp_label(self):
        from gaius.engine.services.clt_skos_label import run_acp_label
        from gaius.storage.database import get_database_url
        import asyncpg

        run_id = str(getattr(self, "_lineage_run_id", "") or "clt-skos")

        async def _run() -> dict:
            pool = await asyncpg.create_pool(get_database_url())
            try:
                return await run_acp_label(pool, run_id=run_id)
            finally:
                await pool.close()

        self.label_stats = asyncio.run(_run())
        print(f"clt_skos.acp_label {self.label_stats}")
        self.next(self.acp_align)

    @step
    def acp_align(self):
        from gaius.engine.services.clt_skos_align import run_acp_align
        from gaius.storage.database import get_database_url
        import asyncpg

        run_id = str(getattr(self, "_lineage_run_id", "") or "clt-skos")

        async def _run() -> dict:
            pool = await asyncpg.create_pool(get_database_url())
            try:
                return await run_acp_align(pool, run_id=run_id)
            finally:
                await pool.close()

        self.align_stats = asyncio.run(_run())
        print(f"clt_skos.acp_align {self.align_stats}")
        self.next(self.end)

    @step
    def end(self):
        print(
            f"clt_skos.end admit={self.admit_stats} extract={self.extract_stats} "
            f"propose={getattr(self, 'propose_stats', {})} "
            f"label={getattr(self, 'label_stats', {})} "
            f"align={getattr(self, 'align_stats', {})}"
        )
        self.emit_lineage_complete(
            outputs=[Dataset.from_source("postgres", "activation")]
        )


if __name__ == "__main__":
    from gaius.flows.config import apply_metaflow_config

    apply_metaflow_config()
    CltSkosEvalFlow()
