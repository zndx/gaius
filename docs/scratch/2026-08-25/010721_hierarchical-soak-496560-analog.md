# Hierarchical soak: analog 496560 (01:07Z)

Jsonl sampler `pid 36619` (~11.2 h, sample-only) still up. Hour **496560**
closed at 01:00Z. Analog HDF5 + Polarisfork append + **DROP RANGE 496560**
this tick. Live hour **496561** is Kudu-only (engine FDW INSERT). Impala
FE already `IMPALA_BUILD_OK`. Sidecar Kudu writer stays retired.

Engine `pid 4115269` (started 21:16:19 this life) still up. Ingest
`ticks=13410 inserted=80460` by 01:06:46. Lag ~0.3 s.

## Proven (no fake rows)

- Closed-hour analog from **FDW Kudu** (engine writer): **21048** rows →
  `gpu_metrics_hour_496560.h5` (207575 B) on analog + Iceberg data
  prefixes. Polarisfork `FileFormat.HDF5`. Jsonl for that hour is
  **21600** rows (3600 ticks) — short **92** warehouse ticks (00:09
  analog/DROP catalog stall). Analog used warehouse rows, not padded
  jsonl. HS2/FDW `gpu_metrics_tier1` GROUP BY includes **21048** for
  496560 (3508 ticks × 6 GPUs). Sample `power_w=115/120/124` `mem=21435`
  on GPUs 0–2 (int16 analog of real DCGM); hour max `power_w=145/142/155/158`
  `util=100` `mem=21435` on GPUs 0–3.
- **DROP RANGE VALUE = 496560** verified (catalog reload fault; SHOW
  RANGE left `496561` … `496582`). UNION no longer double-counts (was
  42096 = 21048×2 before DROP):

  | hour   | store   | count |
  |--------|---------|-------|
  | 496557 | Iceberg | 20532 |
  | 496558 | Iceberg | 21036 |
  | 496559 | Iceberg | 21030 |
  | 496560 | Iceberg | 21048 |
  | 496561 | Kudu    | live  |

- Live lag ~0.3 s. Sample `power_w=122–133` `mem=21435` on GPUs 0–3,
  gpu-5 `mem=3` (real DCGM). Strip=1h UI+CLI `driver=warehouse`,
  `n_times=3600`, matrix **72000**, epoch 01:07:15Z. gpu-0..5 nonzero
  3504/3600 (honest recycle gaps).

Live `gpu_metrics` VIEW is still `tier0 UNION ALL tier1` **without**
`NOT IN`. Honest after DROP. Did not `ALTER VIEW` or `ADD RANGE` extra
hours this tick (catalog mutation; ranges `496561`–`496582` already
cover the live hour).

## Next

Analog **496561** after 02:00Z close, then DROP RANGE 496561. Retry
`ALTER VIEW … NOT IN` when HMS accepts `alter_table`. Do not analog
the open hour. Keep sampler 36619 and engine ingest.
