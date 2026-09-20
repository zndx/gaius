# Theta historical weeks: Airflow backfill, not DAG catchup (2026-09-20)

Catch-up was refused because Theta asks "what ran in this time window?"
After a long miss the implicit window would swallow every closed week at
once, hold the LIGHT token, and cascade missed SLAs on other catalogued
DAGs.

Airflow 3 backfill is the bounded facility:

- `gaius_theta_cycle` stays `catchup=False` (unpause is not a stampede).
- `just theta-backfill --from-date … --to-date …` → `POST /api/v2/backfills`
  with `max_active_runs=1`, `reprocess_behavior=failed`, latest Monday first.
- Each Monday 06:00 logical date consolidates **that** previous ISO week
  (`zndx.logical_date` on the activity postures). Not wall-clock "last week."
- Historical `theta_consolidation_runs` rows are not superseded as stale.

A miss remains a persistent Nautilus / workspace failure until a successful
`source=airflow` tick for the closed week.
