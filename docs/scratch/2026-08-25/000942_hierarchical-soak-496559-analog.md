# Hierarchical soak: analog 496559 (00:09Z)

Jsonl sampler `pid 36619` (~10.3 h, sample-only) still up. Hour **496559**
closed at 00:00Z. Analog HDF5 + Polarisfork append + **DROP RANGE 496559**
this tick. Live hour **496560** is Kudu-only (engine FDW INSERT). Impala
FE already `IMPALA_BUILD_OK`. Sidecar Kudu writer stays retired.

Engine `pid 4115269` (started 21:16:19 this life) still up. Ingest
`ticks=10050 inserted=60300` by 00:09:14. Lag ~0.6 s.

## Proven (no fake rows)

- Closed-hour analog from **FDW Kudu** (engine writer): **21030** rows →
  `gpu_metrics_hour_496559.h5` (207407 B) on analog + Iceberg data
  prefixes. Polarisfork `FileFormat.HDF5`. Jsonl for that hour is
  **21594** rows (3599 ticks) — short **94** warehouse ticks (23:07
  analog/DROP catalog stall). Analog used warehouse rows, not padded
  jsonl. HS2/FDW `gpu_metrics_tier1` GROUP BY includes **21030** for
  496559 (3505 ticks × 6 GPUs). Sample `power_w=116/118/129` `mem=21435`
  on GPUs 0–2 (int16 analog of real DCGM); hour max `power_w=121/123/134/136`
  `util=100` `mem=21435` on GPUs 0–3.
- **DROP RANGE VALUE = 496559** verified (catalog reload fault; SHOW
  RANGE left `496560` … `496582`). UNION no longer double-counts (was
  42060 = 21030×2 before DROP):

  | hour   | store   | count |
  |--------|---------|-------|
  | 496556 | Iceberg | 16164 |
  | 496557 | Iceberg | 20532 |
  | 496558 | Iceberg | 21036 |
  | 496559 | Iceberg | 21030 |
  | 496560 | Kudu    | live  |

- Live lag ~0.6 s. Sample `power_w=112–131` `mem=21435` on GPUs 0–3,
  gpu-5 `mem=3` (real DCGM). Strip=1h UI+CLI `driver=warehouse`,
  `n_times=3600`, matrix **72000**, epoch 00:09:27Z. gpu-0..5 nonzero
  3503/3600 (honest recycle gaps).

Live `gpu_metrics` VIEW is still `tier0 UNION ALL tier1` **without**
`NOT IN`. Honest after DROP. Did not `ALTER VIEW` or `ADD RANGE` extra
hours this tick (catalog mutation; ranges `496560`–`496582` already
cover the live hour).

## Next

Analog **496560** after 01:00Z close, then DROP RANGE 496560. Retry
`ALTER VIEW … NOT IN` when HMS accepts `alter_table`. Do not analog
the open hour. Keep sampler 36619 and engine ingest.
