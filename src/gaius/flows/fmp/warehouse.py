"""FmpWarehouseFlow — typed THS land from the FMP tool catalog.

Metabase (or CLI) asks Gaius to prepare warehouse tables. This flow is the
vessel: FmpCall → flatten → Kudu fmp_*_tier0 (impala_fdw) → ProjectWarehouse.
Thinking writes a narrative only; IRIs are the declared scratch map.
Polarisfork Iceberg is a copy; Metabase reads warehouse.v_fmp_*.
"""
from __future__ import annotations

import json
import os

from metaflow import Parameter, current, step

from gaius.flows import register_flow
from gaius.flows.base import GaiusFlow


@register_flow("fmp-warehouse")
class FmpWarehouseFlow(GaiusFlow):
    gpu_tokens = 0
    scheduled_task_id = Parameter("scheduled-task-id", default=0, type=int)
    symbols = Parameter("symbols", default="", type=str)
    tools = Parameter("tools", default="quote,filings,calendar", type=str)

    @step
    def start(self):
        from gaius.flows.config import apply_metaflow_config
        from gaius.flows.lattice import require_signals_metaflow

        apply_metaflow_config()
        require_signals_metaflow()
        self.symbol_list = [s.strip().upper() for s in str(self.symbols).split(",") if s.strip()]
        self.tool_list = [t.strip().lower() for t in str(self.tools).split(",") if t.strip()]
        if not self.symbol_list:
            raise RuntimeError("#FMP.00000010.WAREHOUSE symbols required")
        print(f"fmp.warehouse.start symbols={self.symbol_list} tools={self.tool_list}")
        self.next(self.fetch)

    @step
    def fetch(self):
        import asyncio

        from gaius.engine.services.fmp_tools import call_tool
        from gaius.hx.fmp_warehouse import FLATTEN

        async def _pull():
            gathered: dict[str, list] = {}
            for tool in self.tool_list:
                key = "profile" if tool in ("quote", "profile") else (
                    "earnings" if tool in ("calendar", "earnings") else tool
                )
                gathered.setdefault(key, [])
                for sym in self.symbol_list:
                    raw = await call_tool(tool, {"symbol": sym, "query": sym, "limit": 8})
                    if raw.get("error"):
                        print(f"WARN {tool} {sym}: {raw['error']}")
                        continue
                    fn = FLATTEN.get(key) or FLATTEN.get(tool)
                    if fn is None:
                        continue
                    gathered[key].extend(fn(list(raw.get("items") or [])))
            return gathered

        self.tables = asyncio.run(_pull())
        print("fmp.warehouse.fetch " + json.dumps({k: len(v) for k, v in self.tables.items()}))
        self.next(self.land)

    @step
    def land(self):
        from gaius.hx.fmp_warehouse import land

        self.landed = []
        for name, rows in self.tables.items():
            if name not in ("profile", "filings", "earnings"):
                continue
            result = land(name, rows)
            self.landed.append(result)
            print(f"fmp.warehouse.land {result}")
        if not any(t.get("rows") for t in self.landed):
            raise RuntimeError("#FMP.00000010.WAREHOUSE no rows landed")
        self.next(self.notify)

    @step
    def notify(self):
        from gaius.engine.services.fmp_warehouse import notify_metabase

        # FederationSurfaces project=metabase; env is an override, not a default.
        target = (os.environ.get("METABASE_ENGINE_TARGET") or "").strip()
        self.notify_result = notify_metabase(tables=self.landed, engine_target=target)
        print(f"fmp.warehouse.notify {self.notify_result}")
        self.next(self.end)

    @step
    def end(self):
        print(
            f"fmp.warehouse.end landed={self.landed} notify={getattr(self, 'notify_result', None)} "
            f"run={getattr(current, 'run_id', '')}"
        )


if __name__ == "__main__":
    from gaius.flows.config import apply_metaflow_config

    apply_metaflow_config()
    FmpWarehouseFlow()
