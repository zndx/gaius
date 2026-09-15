# gaius.theta.cycle — scratch THS (2026-09-14)

Product `gaius.theta.cycle` is materialized over **scratch** storage:
`signals_dataproducts.theta_scratch_{vertex,edge,incidence}_tier0` (Kudu),
FDW twins on Gaius `:5444` and Signals `:5455`.

Hypergraph incidence (not AGE): one remainder window × CLT feature × label
is an n-ary edge. Graph analysis / hubs is later **data-fusion over settled
Iceberg**. AGE remains Atlas+OL only.

Expire: `DROP RANGE PARTITION` on `epoch_hour` after Iceberg verify; never
row `DELETE`. Polar Iceberg tier1 is the settle PR (no Impala `STORED AS
ICEBERG` — MultiMetaProvider phantom-table incident).

HX `llm.generations` / `hx.cot_reasoning` and CLT admit/label clocks are
unchanged; Theta reads them.

Polar Iceberg `theta_scratch_*_tier1` registered 2026-09-14 (hour identity
partition). Kudu `schema-apply` still needs a Signals devenv with impyla.
Remainder windows (`none`/`ambiguous`) INSERT `theta_cycle_vertex_tier0`
fail-open from `gather_slices`.

2026-09-15: ThetaCycleFlow is the **consolidation consumer** (NVAR → BERTSubs
→ KG) for `theta_consolidation_runs`. It does **not** DROP Kudu ranges or
expire Iceberg. pg_cron still only INSERTs `scheduled` rows; Airflow
`gaius_theta_cycle` Monday 06:00 drains them. Remainder vertices are no
longer written from gather_slices.
