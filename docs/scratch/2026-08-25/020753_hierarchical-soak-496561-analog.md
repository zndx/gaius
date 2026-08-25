# Hierarchical soak: analog 496561 (02:07Z)

Jsonl sampler `pid 36619` (~12.2 h, sample-only) still up. Hour **496561**
closed at 02:00Z. Analog HDF5 + Polarisfork append + **DROP RANGE 496561**
this tick (`gpu-metrics-settle` pg_cron did not analog; soak did).
Live hour **496562** is Kudu-only (engine FDW INSERT). Impala FE already
`IMPALA_BUILD_OK`. Sidecar Kudu writer stays retired.

Engine `pid 4115269` (started 21:16:19 this life) still up. Ingest
`ticks=16950 inserted=101700` by 02:07:19. Lag ~0.9 s.

## Proven (no fake rows)

- Closed-hour analog from **FDW Kudu** (engine writer): **21030** rows →
  `gpu_metrics_hour_496561.h5` (207407 B) on analog + Iceberg data
  prefixes. Polarisfork `FileFormat.HDF5`. Jsonl for that hour is
  **21594** rows (3599 ticks) — short **94** warehouse ticks (01:07
  analog/DROP catalog stall). Analog used warehouse rows, not padded
  jsonl. HS2/FDW `gpu_metrics_tier1` GROUP BY includes **21030** for
  496561 (3505 ticks × 6 GPUs). Sample `power_w=120/122/131` `mem=21435`
  on GPUs 0–2 (int16 analog of real DCGM); hour max `power_w=147/145/160/164`
  `util=100` `mem=21435` on GPUs 0–3.
- **DROP RANGE VALUE = 496561** verified (catalog reload fault; SHOW
  RANGE left `496562` … `496582`). UNION no longer double-counts (was
  42060 = 21030×2 before DROP):

  | hour   | store   | count |
  |--------|---------|-------|
  | 496558 | Iceberg | 21036 |
  | 496559 | Iceberg | 21030 |
  | 496560 | Iceberg | 21048 |
  | 496561 | Iceberg | 21030 |
  | 496562 | Kudu    | live  |

- Live lag ~0.9 s. Sample `power_w=118–127` `mem=21435` on GPUs 0–3,
  gpu-5 `mem=3` (real DCGM). Strip=1h UI+CLI `driver=warehouse`,
  `n_times=3600`, matrix **72000**, epoch 02:07:47Z. gpu-0..5 nonzero
  3505/3600 (honest recycle gaps).

Live `gpu_metrics` VIEW is still `tier0 UNION ALL tier1` **without**
`NOT IN`. Honest after DROP. Did not `ALTER VIEW` or `ADD RANGE` extra
hours this tick (catalog mutation; ranges `496562`–`496582` already
cover the live hour).

## Next

Analog **496562** after 03:00Z close, then DROP RANGE 496562. Retry
`ALTER VIEW … NOT IN` when HMS accepts `alter_table`. Do not analog
the open hour. Keep sampler 36619 and engine ingest.
