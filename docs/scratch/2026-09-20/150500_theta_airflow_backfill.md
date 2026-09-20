# Theta historical weeks: Airflow backfill, not DAG catchup (2026-09-20)

Catch-up was refused because Theta asks "what ran in this time window?"
After a long miss the implicit window would swallow every closed week at
once, hold the LIGHT token, and cascade missed SLAs on other catalogued
DAGs.

Airflow 3 backfill is the bounded facility:

- `gaius_theta_cycle` stays `catchup=False` (unpause is not a stampede).
- Default `just theta-backfill` triggers **one DAG run per UTC day**.
  Each day stamps `zndx.window_date`; Gaius encodes that day's thoughts
  and merges them into the **same** `theta_consolidation_runs` row for the
  containing ISO week. The product is the week consolidation, not seven
  day-bounded slices.
- The week row completes when metadata.windows covers Monday–Sunday.
- `--weekly` is the coarse Airflow backfill (one Monday logical date per week).
- `zndx.logical_date` without a window date still means "previous ISO week"
  (on-time Monday 06:00).
- Historical `theta_consolidation_runs` rows are not superseded as stale.

A miss remains a persistent Nautilus / workspace failure until a successful
`source=airflow` tick for the closed week.
