"""ThetaCycleFlow — NVAR → BERTSubs → knowledge-gradient consolidation.

Consumes ``theta_consolidation_runs`` rows that pg_cron has queued since
2026-W26 and never executed. Airflow DAG ``gaius_theta_cycle`` (Monday 06:00).

    uv run python -m gaius.flows.theta.cycle run
"""

from __future__ import annotations

import asyncio
import os

from metaflow import Parameter, current, step

from gaius.flows import register_flow
from gaius.flows.base import GaiusFlow
from gaius.hx.lineage.events import Dataset


@register_flow("theta-cycle")
class ThetaCycleFlow(GaiusFlow):
    """The Theta consolidation cycle. Not a THS janitor."""

    scheduled_task_id = Parameter("scheduled-task-id", default=0, type=int)
    max_jobs = Parameter("max-jobs", default=10, type=int)

    @step
    def start(self):
        from gaius.flows.config import apply_metaflow_config
        from gaius.flows.lattice import require_signals_metaflow

        apply_metaflow_config()
        require_signals_metaflow()
        self.run_id = str(getattr(current, "run_id", None) or "")
        print(
            f"theta.cycle.start run_id={self.run_id} task={self.scheduled_task_id} "
            f"max_jobs={self.max_jobs}"
        )
        self.emit_lineage_start(
            job_name="theta_cycle",
            inputs=[Dataset.from_source("postgres", "theta_consolidation_runs")],
        )
        self.next(self.consolidate)

    @step
    def consolidate(self):
        from gaius.engine.services.theta_cycle import consume_pending, engine_consolidator
        from gaius.storage.database import get_database_url
        import asyncpg

        max_jobs = int(self.max_jobs)

        async def _go():
            pool = await asyncpg.create_pool(get_database_url())
            try:
                async with pool.acquire() as conn:
                    return await consume_pending(
                        conn,
                        consolidator=engine_consolidator,
                        max_jobs=max_jobs,
                    )
            finally:
                await pool.close()

        self.jobs = asyncio.run(_go())
        print(f"theta.cycle.consolidate jobs={self.jobs}")
        self.next(self.end)

    @step
    def end(self):
        jobs = getattr(self, "jobs", []) or []
        failed = [j for j in jobs if not j.get("success") and not j.get("skipped")]
        print(f"theta.cycle.end n={len(jobs)} failed={len(failed)}")
        self.emit_lineage_complete(
            outputs=[Dataset.from_source("postgres", "theta_consolidation_runs")]
        )
        if failed:
            raise RuntimeError(
                "#THETA.00000005.CONSFAIL "
                + ", ".join(f"{j.get('slice_id')}:{j.get('error')}" for j in failed)
            )


if __name__ == "__main__":
    from gaius.flows.config import apply_metaflow_config

    apply_metaflow_config()
    ThetaCycleFlow()
