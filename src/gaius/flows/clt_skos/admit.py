"""CltSkosAdmitFlow — incremental MaxSim admit + CLT extract.

Overlapping fetched_at watermark; admitted_item is the idempotency key.
#WS.00000019 quarantines; extract backfill reopens the same cursor.
ACP labeling is a separate task_type.

    uv run python -m gaius.flows.clt_skos.admit run
"""

from __future__ import annotations

import asyncio
import os

from metaflow import Parameter, current, step

from gaius.flows import register_flow
from gaius.flows.base import GaiusFlow
from gaius.hx.lineage.events import Dataset


@register_flow("clt-skos-admit")
class CltSkosAdmitFlow(GaiusFlow):
    """Living corpus: admit new inbound docs, extract CLT on new windows."""

    batch = Parameter("batch", help="Docs per tick", default=16, type=int)
    gpu_index = Parameter("gpu-index", help="CLT GPU", default=4, type=int)
    extract_top_k = Parameter("extract-top-k", help="Top-k per position", default=16, type=int)
    skip_extract = Parameter("skip-extract", default=False, type=bool)
    scheduled_task_id = Parameter("scheduled-task-id", default=0, type=int)

    @step
    def start(self):
        from gaius.engine.services.clt_skos_aperture import materialize_aperture
        from gaius.engine.services.sdg_aperture import SdgAperture

        self.aperture = SdgAperture.load()
        self.index = materialize_aperture(self.aperture)
        self.run_id = str(getattr(current, "run_id", None) or self._lineage_run_id or "")
        print(
            f"clt_skos.admit.start strategy={self.aperture.strategy_id} "
            f"C={self.aperture.n} tau={self.aperture.tau} "
            f"run_id={self.run_id} task={self.scheduled_task_id}"
        )
        self.emit_lineage_start(
            job_name="clt_skos_admit",
            inputs=[Dataset.from_source("postgres", "content_items")],
        )
        if not self.run_id:
            self.run_id = str(self._lineage_run_id or "")
        print(f"clt_skos.run_id={self.run_id}")
        self.next(self.admit)

    @step
    def admit(self):
        from gaius.engine.services.clt_skos_clock import run_admit_tick
        from gaius.storage.database import get_database_url
        import asyncpg

        task_id = int(self.scheduled_task_id or os.environ.get("GAIUS_SCHEDULED_TASK_ID") or 0)

        async def _run() -> dict:
            pool = await asyncpg.create_pool(get_database_url())
            try:
                return await run_admit_tick(
                    pool,
                    run_id=str(self.run_id),
                    task_id=task_id,
                    batch=int(self.batch),
                    gpu_index=int(self.gpu_index),
                    extract_top_k=int(self.extract_top_k),
                    skip_extract=bool(self.skip_extract),
                )
            finally:
                await pool.close()

        self.stats = asyncio.run(_run())
        print(f"clt_skos.admit.tick {self.stats}")
        self.next(self.end)

    @step
    def end(self):
        print(f"clt_skos.admit.end {getattr(self, 'stats', {})}")
        self.emit_lineage_complete(
            outputs=[Dataset.from_source("postgres", "admitted_item")]
        )


if __name__ == "__main__":
    from gaius.flows.config import apply_metaflow_config

    apply_metaflow_config()
    CltSkosAdmitFlow()
