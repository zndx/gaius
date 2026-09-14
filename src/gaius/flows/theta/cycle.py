"""ThetaCycleFlow — gaius.theta.cycle (Metaflow, Airflow-orchestrated).

One flow: analog closed Kudu hours into Iceberg, DROP RANGE after verify,
expire whole Iceberg hour partitions, delete orphan files.

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
    """Product flow for gaius.theta.cycle. Scratch is the THS tablet family."""

    apply = Parameter("apply", help="Write Iceberg / DROP / expire (default on)", default=True, type=bool)
    retain_hours = Parameter(
        "retain-hours",
        help="Iceberg hours to keep (default 34 days)",
        default=816,
        type=int,
    )
    scheduled_task_id = Parameter("scheduled-task-id", default=0, type=int)

    @step
    def start(self):
        from gaius.flows.config import apply_metaflow_config
        from gaius.flows.lattice import require_signals_metaflow

        apply_metaflow_config()
        require_signals_metaflow()
        self.run_id = str(getattr(current, "run_id", None) or "")
        print(
            f"theta.cycle.start apply={self.apply} retain_hours={self.retain_hours} "
            f"run_id={self.run_id} task={self.scheduled_task_id}"
        )
        self.emit_lineage_start(
            job_name="theta_cycle",
            inputs=[Dataset.from_source("kudu", "theta_scratch_vertex_tier0")],
        )
        self.next(self.settle)

    def _run(self, **flags):
        from gaius.engine.services.theta_cycle import run_cycle
        from gaius.storage.database import get_database_url
        import asyncpg

        apply = bool(self.apply)
        retain = int(self.retain_hours)

        async def _go():
            pool = await asyncpg.create_pool(get_database_url())
            try:
                async with pool.acquire() as conn:
                    return await run_cycle(
                        conn, apply=apply, retain_hours=retain, **flags
                    )
            finally:
                await pool.close()

        return asyncio.run(_go())

    @step
    def settle(self):
        """Copy closed Kudu hours into Polar Iceberg."""
        self.report = self._run(analog=True, drop=False, expire=False)
        print(f"theta.cycle.settle analoged={self.report.analoged}")
        self.next(self.maintain)

    @step
    def maintain(self):
        """DROP RANGE on verified hours; expire Iceberg partitions; orphan GC."""
        maint = self._run(analog=False, drop=True, expire=True)
        prev = getattr(self, "report", None)
        self.report = maint
        if prev is not None:
            maint.analoged = list(prev.analoged)
        print(
            f"theta.cycle.maintain dropped={maint.dropped} expired={maint.expired}"
        )
        self.next(self.end)

    @step
    def end(self):
        print(f"theta.cycle.end {getattr(self, 'report', None)}")
        self.emit_lineage_complete(
            outputs=[Dataset.from_source("iceberg", "theta_scratch_vertex_tier1")]
        )


if __name__ == "__main__":
    from gaius.flows.config import apply_metaflow_config

    apply_metaflow_config()
    ThetaCycleFlow()
