# Hierarchical soak: analog 496557 (22:09Z)

Jsonl sampler `pid 36619` (~8.3 h, sample-only) still up. Hour **496557**
closed at 22:00Z. Analog HDF5 + Polarisfork append + **DROP RANGE 496557**
this tick. Live hour **496558** is Kudu-only (engine FDW INSERT). Impala
FE already `IMPALA_BUILD_OK`. Sidecar Kudu writer stays retired.

Engine `pid 4115269` (started 21:16:19 this life) still up. Ingest
`ticks=3060 inserted=18360` by 22:09:38. Lag ~0.4 s.

## Proven (no fake rows)

- Closed-hour analog from **FDW Kudu** (engine writer): **20532** rows →
  `gpu_metrics_hour_496557.h5` (202759 B) on analog + Iceberg data
  prefixes. Polarisfork `FileFormat.HDF5`. Jsonl for that hour is
  **21588** rows (3598 ticks) — short **176** warehouse ticks (21:16
  recycle stall). Analog used warehouse rows, not padded jsonl. HS2/FDW
  `gpu_metrics_tier1` GROUP BY includes **20532** for 496557 (3422 ticks
  × 6 GPUs). Sample `power_w=110/113/116` `util=100` `mem=21431` on
  GPUs 0–2 (int16 analog of real DCGM); hour max `power_w=130/131/145/145`
  `util=100` `mem=21435` on GPUs 0–3.
- **DROP RANGE VALUE = 496557** verified (catalog reload fault; SHOW
  RANGE left `496558` … `496582`). UNION no longer double-counts (was
  41064 = 20532×2 before DROP):

  | hour   | store   | count |
  |--------|---------|-------|
  | 496554 | Iceberg | 13974 |
  | 496555 | Iceberg | 12486 |
  | 496556 | Iceberg | 16164 |
  | 496557 | Iceberg | 20532 |
  | 496558 | Kudu    | live  |

- Live lag ~0.4 s. Sample `power_w=113–126` `mem=21435` on GPUs 0–3,
  gpu-5 `mem=3` (real DCGM). Strip=1h UI+CLI `driver=warehouse`,
  `n_times=3600`, matrix **72000**, epoch 22:09:34Z. gpu-0..5 nonzero
  3429/3600 (honest recycle gaps).

Live `gpu_metrics` VIEW is still `tier0 UNION ALL tier1` **without**
`NOT IN`. Honest after DROP. Did not `ALTER VIEW` or `ADD RANGE` extra
hours this tick (catalog mutation; ranges `496558`–`496582` already
cover the live hour).

## Next

Analog **496558** after 23:00Z close, then DROP RANGE 496558. Retry
`ALTER VIEW … NOT IN` when HMS accepts `alter_table`. Do not analog
the open hour. Keep sampler 36619 and engine ingest.
