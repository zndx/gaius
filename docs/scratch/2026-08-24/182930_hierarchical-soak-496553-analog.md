# Hierarchical soak: analog 496553 (18:29Z)

Jsonl sampler `pid 36619` (~4.6 h, sample-only) and engine
`pid 2427158` (started 18:11:56Z this life) still up. Hour **496553**
closed at 18:00Z. Live hour **496554** is Kudu-only (engine FDW INSERT).
Impala FE already `IMPALA_BUILD_OK`. Sidecar Kudu writer stays retired.

## Proven (no fake rows)

- Closed-hour analog from **FDW Kudu** (engine writer): **16770** rows →
  `gpu_metrics_hour_496553.h5` (167647 B) on analog + Iceberg data
  prefixes. Jsonl for that hour is **21588** rows (3598 ticks) — short
  **803** warehouse ticks (17:27 / 17:50 recycles; engine this life
  started 18:11Z so the last ~11 min of 496553 never landed). Analog
  used warehouse rows, not padded jsonl. Polarisfork `FileFormat.HDF5`.
  HS2/FDW `gpu_metrics_tier1` GROUP BY includes **16770** for 496553.
  Sample `power_w=46` `util=0` `mem=24027` on gpu-0 (int16 analog of
  DCGM `46.062` / `24027` after `gpu_cleanup`; other GPUs idle `mem=3`).
- **DROP RANGE VALUE = 496553** verified (catalog reload fault; SHOW
  RANGE left `496554` … `496573` after ADD 570–573). UNION no longer
  double-counts (was 33540 = 16770×2 before DROP):

  | hour   | store   | count |
  |--------|---------|-------|
  | 496550 | Iceberg | 20334 |
  | 496551 | Iceberg | 20460 |
  | 496552 | Iceberg | 20430 |
  | 496553 | Iceberg | 16770 |
  | 496554 | Kudu    | live  |

- Live lag ~0.6 s. Sample `power_w≈111–125` `util=100` `mem=21439`
  on GPUs 0–3 (thinking). Strip=1h UI+CLI `driver=warehouse`,
  `n_times=3600`, `n_channels=20`, matrix **72000**. gpu-0..5
  nonzero 2083/3600 (honest recycle gaps, newest cols packed busy).

Live `gpu_metrics` VIEW is still `tier0 UNION ALL tier1` **without**
`NOT IN`. Honest after DROP; analog-before-DROP next hour will
double-count until DROP or the view lands. `impala_fdw_exec` rejects
`ADD IF NOT EXISTS` (`#SL.00000029.RANGEDDL`); bare
`ADD RANGE PARTITION VALUE = <hour>` works.

## Next

Analog **496554** after 19:00Z close. Retry `ALTER VIEW … NOT IN` when
HMS accepts `alter_table`. Do not analog the open hour. Keep sampler
36619 and engine ingest.
