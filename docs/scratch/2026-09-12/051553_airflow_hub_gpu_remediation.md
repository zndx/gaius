# Airflow hub vs pg_cron GPU dual-map (2026-09-12)

GPU occupancy that looked like Airflow was **not** an Airflow DAG. Cards 0–3
are resident `vLLM serve Qwen/Qwen3.8-27B` TP=4 (`gaius-thinking`). Live 100%
util was Metaflow `ambient.synthesis_flow` / `market_buffer_flow` spawned by
**pg_cron** while `gaius_ambient_synthesis` and `gaius_fmp_roll` sat **paused**.

## Dual-map

- pg_cron `ambient-synthesis` (`*/20`) and `fmp-roll` (`7,37 * * * *`) were
  still `active=true` after `20260911000001` (that migration only retired
  publish-cards / prospects / weekly-signals twins).
- Signals `ListWorkloads`: those two `source=pg_cron`, DAG `state=paused`.
- Airflow workers idle; Metaflow CLI still ran.

Fix: `20260912000001_airflow_only_ambient_and_fmp.sql` deactivates the jobs;
catalogue `enabled=True` so `Scheduler/SyncWorkloads` materialises the DAGs.
Applied live. One-off `WorkloadSync` submitted the new catalogue;
`gaius_ambient_synthesis` / `gaius_fmp_roll` are **unpaused**.

The running `gaius-engine` still has the **old** in-memory catalogue. Its next
30 min `SyncWorkloads` (last 04:58 UTC) will re-pause unless restarted or a
follow-up sync from the new catalogue wins. Restart after article_curate
`#40200` finishes so Yield/skip-row code loads without killing the catch-up.

## MISSTICK `article_curate`, `prospects_check`

Airflow **did** run `gaius_article_curate` on 10 and 11 Sep (`hold` ~182s then
success). Gaius had **no** `scheduled_tasks` row: the lease **lapsed** (180s
TTL, no heartbeat) and `close()` treated `lapsed` as DAG success. That is the
same class of bug as pg_cron cover — the hub looks green while the peer did
not run.

`should_run_curation()` is true now. Manual run
`manual__misstick_20260912T0516` → Gaius `article_curate #40200` `source=airflow`
picked up 05:17 UTC.

`prospects_check`: gate `meta.should_run_prospects_check()` is **false**; last
real work was pg_cron 11 Sep 07:00 (attached, source stayed pg_cron). Do not
force a tick. Coordination now stamps attached rows `source=airflow` and
inserts a skipped airflow row when the gate is false, so MISSTICK counts a
real hub tick.

Signals `coord_lease.require_released`: only `released` closes success;
`lapsed` raises `#CO.0000000E.LAPSED`. Plugin is in-tree; live Airflow still
runs the ConfigMap copy until `scripts/airflow_dags_deploy.sh`.

## YK zombie `clt-skos-admit-36884`

Running since 9 Sep 21:15 on `root.internal.inference.light` (1 GPU) with no
matching host process; nvidia-smi GPU 5 empty; YK node 6/6. `Engine/Yield`
(old process) returned `no host process` without deleting the sentinel.
`kubectl -n federation-signals delete pod clt-skos-admit-36884` retired it
(Completing, used={}). New `yield_workload` retires unknown ids via
`delete_flow_sentinel` — needs engine restart to load.

## Commits

- gaius `45e1082` catalogue + migration
- gaius `958d0d1` skipped/attached rows count as airflow
- gaius `b85fc73` Yield orphan retires sentinel
- signals `7f0c1a9` lapse fails the DAG
