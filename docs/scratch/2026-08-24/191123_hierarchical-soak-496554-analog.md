# Hierarchical soak: analog 496554 (19:11Z)

Jsonl sampler `pid 36619` (~5.3 h, sample-only) still up. Hour **496554**
closed at 19:00Z. Live hour **496555** is Kudu-only (engine FDW INSERT).
Impala FE already `IMPALA_BUILD_OK`. Sidecar Kudu writer stays retired.

Engine `pid 2807451` died ~19:00Z (`:50051` down, ProcessLookupError on
vLLM stop). Restarted via `devenv processes restart gaius-engine`
(`pid 2967194`, ingest `ticks=1` at 19:10:52).

## Proven (no fake rows)

- Closed-hour analog from **FDW Kudu** (engine writer): **13974** rows →
  `gpu_metrics_hour_496554.h5` (141551 B) on analog + Iceberg data
  prefixes. Jsonl for that hour is **21558** rows (3593 ticks) — short
  **1264** warehouse ticks (18:00–18:11 start plus 18:33 / 18:49
  recycles). Analog used warehouse rows, not padded jsonl. Polarisfork
  `FileFormat.HDF5`. HS2/FDW `gpu_metrics_tier1` GROUP BY includes
  **13974** for 496554. Sample `power_w=74/83/84` `util=100` `mem=21337`
  on GPUs 1–3 (int16 analog of real DCGM).
- **DROP RANGE VALUE = 496554** verified (catalog reload fault; SHOW
  RANGE left `496555` … `496574` after ADD 574). UNION no longer
  double-counts (was 27948 = 13974×2 before DROP):

  | hour   | store   | count |
  |--------|---------|-------|
  | 496551 | Iceberg | 20460 |
  | 496552 | Iceberg | 20430 |
  | 496553 | Iceberg | 16770 |
  | 496554 | Iceberg | 13974 |
  | 496555 | Kudu    | live  |

- Live lag ~0.2 s after restart. Sample `power_w=7.9–20.4` `mem=3`
  (real DCGM after `gpu_cleanup`). Strip=1h UI+CLI `driver=warehouse`,
  `n_times=3600`, matrix **72000**. gpu-0..5 nonzero 2272/3600 (honest
  recycle/engine-down gaps).

Live `gpu_metrics` VIEW is still `tier0 UNION ALL tier1` **without**
`NOT IN`. Honest after DROP.

## Next

Analog **496555** after 20:00Z close. Retry `ALTER VIEW … NOT IN` when
HMS accepts `alter_table`. Do not analog the open hour. Keep sampler
36619 and engine ingest.
