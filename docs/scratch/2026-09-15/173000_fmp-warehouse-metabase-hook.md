# FMP relational land → Metabase semantic hook

Desired: remote Metabase engine asks Gaius to prepare **typed warehouse
tables** from FMP tools (agent-mediated Metaflow), land them via
**Postgres FDW → THS (Kudu tier0 + Iceberg tier1)**, then gRPC-hook
Metabase to sync schema and project **Atlas entity IRIs** into the
semantic layer. Metabot then sees the tables.

## What already exists

| Piece | Where | Gap vs this story |
|-------|--------|-------------------|
| FMP tool catalog | `fmp_tools.py` / `FmpCall` | JSON items, not relational rows |
| Exchange capture | `raw.fmp_exchange` Iceberg | **JSON blob** per HTTP call, not statements/quotes tables |
| THS / FDW | Impala HS2, `impala_fdw`, `sdg.warehouse.*` (K12) | Proven for cognition strip; **no `warehouse.fmp_*`** |
| Metaflow + Complete | ProspectsUpdate, lattice | Agent-mediated extract exists; **not a warehouse lander** |
| Metabase engine | AGPL `mbengine` `:50451`, capability `dashboard` | Status + GetDashboardInstance only. **No “tables landed” RPC** |
| Metabot federation | `mbengine.engine.federation` maps metabot → Gaius thinking/instruct | Complete only; **does not ingest schema** |
| Model sync | Gaius `MetabaseSyncTrigger` → HTTP `/api/card` over **`meta.*`** | K4: do **not** use `:3100` / `meta.*` for warehouse |
| Semantics | `apply_semantics` name heuristics | Not Atlas IRIs. Designed projector is **K17** (`ScientificProjectMetabase`) — not shipped |
| Atlas | Gaius POSTs OpenLineage to Signals `:21010` | Entities for FMP tables not defined |

## Intended control flow (Kudu + FDW + ProjectWarehouse built 2026-09-15;
Iceberg tier1 settle still PENDING)

```
MetabaseEngine  --zndx.engine.v1-->  GaiusEngine
  "prepare FMP warehouse {symbols, tools}"
        |
        v
  Airflow Activity (Metaflow)
        |  Complete(thinking) to pick/format columns
        |  FmpCall catalog (Starter, no 13F)
        v
  Impala INSERT Kudu fmp_*_tier0
  settle → Iceberg fmp_*_tier1
        |
        v
  Postgres FDW IMPORT → warehouse.v_fmp_*
        |
        v
  Gaius --gRPC--> MetabaseEngine.ProjectWarehouse
        |  POST /api/database/:id/sync_schema
        |  PUT  /api/field/:id  semantic_type + settings.scientific
        |    IRI from Atlas entity / semantic.bindings
        v
  Metabot queries warehouse.v_fmp_* as models
```

Duration of the Metaflow is unbounded; the hook is **completion-driven**,
not a timeout. Fail-closed if thinking is absent, FDW cannot see Kudu,
or Atlas has no binding (`#SL.00000006`).

Do not route warehouse models through Gaius `:3100`. Projector target is
`FederationSurfaces` `project=metabase` / UI `:3200`.
