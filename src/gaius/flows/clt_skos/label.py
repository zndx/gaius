"""CltSkosLabelFlow — ACP/thinking names unlabeled tape-hot features.

Work queue is the ledger (activations ∩ missing/stale skos_pref_label).
Independent of admit. MAX_LABEL=8 is backpressure.

    uv run python -m gaius.flows.clt_skos.label run
"""

from __future__ import annotations

import asyncio
import os

from metaflow import Parameter, current, step

from gaius.flows import register_flow
from gaius.flows.base import GaiusFlow
from gaius.hx.lineage.events import Dataset


@register_flow("clt-skos-label")
class CltSkosLabelFlow(GaiusFlow):
    """Mint skos:prefLabel for tape-hot unlabeled / stale features."""

    max_labels = Parameter("max-labels", default=8, type=int)
    scheduled_task_id = Parameter("scheduled-task-id", default=0, type=int)

    @step
    def start(self):
        self.run_id = str(getattr(current, "run_id", None) or self._lineage_run_id or "")
        self.emit_lineage_start(
            job_name="clt_skos_label",
            inputs=[Dataset.from_source("postgres", "activation")],
        )
        if not self.run_id:
            self.run_id = str(self._lineage_run_id or "")
        print(f"clt_skos.label.start run_id={self.run_id} task={self.scheduled_task_id}")
        print(f"clt_skos.run_id={self.run_id}")
        self.next(self.label)

    @step
    def label(self):
        from gaius.engine.services.clt_skos_label import run_acp_label
        from gaius.storage.database import get_database_url
        import asyncpg

        task_id = int(self.scheduled_task_id or os.environ.get("GAIUS_SCHEDULED_TASK_ID") or 0)

        async def _run() -> dict:
            pool = await asyncpg.create_pool(get_database_url())
            try:
                return await run_acp_label(
                    pool,
                    run_id=str(self.run_id),
                    max_cases=int(self.max_labels),
                    task_id=task_id,
                )
            finally:
                await pool.close()

        try:
            self.stats = asyncio.run(_run())
        except Exception as e:
            self.emit_lineage_fail(str(e))
            raise
        print(f"clt_skos.label.tick {self.stats}")
        self.next(self.end)

    @step
    def end(self):
        print(f"clt_skos.label.end {getattr(self, 'stats', {})}")
        self.emit_lineage_complete(
            outputs=[Dataset.from_source("postgres", "skos_pref_label")]
        )


if __name__ == "__main__":
    from gaius.flows.config import apply_metaflow_config

    apply_metaflow_config()
    CltSkosLabelFlow()
