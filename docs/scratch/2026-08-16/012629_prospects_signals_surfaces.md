# Prospects on Signals Applications, Queues, History

Confirmation of how `prospects-update` / `prospects-check` surface on
the live Signals backplane (`:9889`) after the thinking/K8s rework.

## Applications / Queues — configured

Signals Applications and Queues read YuniKorn live via Engine
`ListQueueApplications` (not a Gaius JSON catalog).

Gaius stamps on admit (`gaius.engine.sentinel_claim`):

| Kind | Queue leaf | Phase | Lifetime |
|------|------------|-------|----------|
| `prospects-update` | `root.internal.inference.extract` | extract | while the GPU claim is up |
| `prospects-compact` / `prospects-summary` | same extract token | compact / summarize | bind, do not mint a second app |
| `prospects-check` | `root.external.rate-metered` | ingest | ephemeral (admit → release) |

`federation.project=gaius` is a label. There is no `root.gaius`.
Envelope is one Gaius Application per leaf: a live
`article-curate-*` on extract is reused (`bind_workload_id`).

Live at confirmation: `article-curate-1786767299` on extract,
`gaius-ambient` on `root.internal.compute`. A prospects update
started now binds the extract claim rather than adding a second GPU
row.

## History — seeded + flow `end` publishes

`gaius.prospects.corpus` was missing from the Signals seed
(`config/platform/data-products.json`). History Inventory therefore
showed only `gaius.cognition.outputs` for Gaius.

Now:

1. Seed includes `gaius.prospects.corpus` (peer `gaius`, kind
   `corpus`, leaf `root.internal.inference.extract`). The running UI
   reads that file (`SIGNALS_DATA_PRODUCTS_PATH`) so the inventory
   row appears without a UI rebuild.
2. `ProspectsUpdateFlow.end` calls
   `gaius.flows.prospects.publish.publish_from_flow`. When Signals is
   on the lattice this shells into `$SIGNALS_ROOT` and records a
   UUIDv7 `tx` via `signals.ops.history.review` (warehouse SoR).
   Standalone devenv skips.

Update-history *event* rows on `/history` still come from
`SIGNALS_DATA_PRODUCT_HISTORY` JSONL. `review()` writes Impala
`details`/`tx`/`hx`, not that JSONL. The inventory card is the
product; event lines appear after Signals UI reads the warehouse
(or a later dual-write). Do not inject History rows in HTML.

## Not this work

Airflow DAG, Overwatch `hx_reasoning` observation, ColBERT aperture
seed, `@kubernetes` on every step.
