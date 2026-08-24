# Hierarchical soak: analog 496558 (23:07Z)

Jsonl sampler `pid 36619` (~9.2 h, sample-only) still up. Hour **496558**
closed at 23:00Z. Analog HDF5 + Polarisfork append this tick. Live hour
**496559** is Kudu-only (engine FDW INSERT). Impala FE already
`IMPALA_BUILD_OK`. Sidecar Kudu writer stays retired.

Engine `pid 4115269` (started 21:16:19 this life) still up. Ingest
`ticks=6420 inserted=38520` by 23:07:09. Lag ~0.6 s.

## Proven (no fake rows)

- Closed-hour analog from **FDW Kudu** (engine writer): **21036** rows →
  `gpu_metrics_hour_496558.h5` (207463 B) on analog + Iceberg data
  prefixes. Polarisfork `FileFormat.HDF5`. Jsonl for that hour is
  **21600** rows (3600 ticks) — short **94** warehouse ticks (22:07
  analog/DROP catalog stall). Analog used warehouse rows, not padded
  jsonl. HS2/FDW `gpu_metrics_tier1` GROUP BY includes **21036** for
  496558 (3506 ticks × 6 GPUs). Sample `power_w=110/114/122` `mem=21435`
  on GPUs 0–2 (int16 analog of real DCGM); hour max `power_w=128/129/143/143`
  `util=100` `mem=21435` on GPUs 0–3.
- **DROP RANGE VALUE = 496558 not applied this tick** (catalog mutation
  blocked). SHOW RANGE still `496558` … `496582`. UNION **double-counts**
  496558 (42072 = 21036×2) until DROP:

  | hour   | store   | count |
  |--------|---------|-------|
  | 496555 | Iceberg | 12486 |
  | 496556 | Iceberg | 16164 |
  | 496557 | Iceberg | 20532 |
  | 496558 | Iceberg+Kudu | 21036×2 |
  | 496559 | Kudu    | live  |

- Live lag ~0.6 s. Sample `power_w=114–131` `mem=21435` on GPUs 0–3,
  gpu-5 `mem=3` (real DCGM). Strip=1h UI+CLI `driver=warehouse`,
  `n_times=3600`, matrix **72000**, epoch 23:07:36Z. gpu-0..5 nonzero
  3504/3600 (honest recycle gaps; strip packs by second so the
  double-counted hour does not inflate `n_times`).

Live `gpu_metrics` VIEW is still `tier0 UNION ALL tier1` **without**
`NOT IN`. Honest only after DROP.

## Next

**DROP RANGE 496558** (approve catalog mutation), then analog **496559**
after 00:00Z close. Retry `ALTER VIEW … NOT IN` when HMS accepts
`alter_table`. Do not analog the open hour. Keep sampler 36619 and
engine ingest.
