# Hierarchical soak: analog 496552 (17:07Z)

Jsonl sampler `pid 36619` (~3.2 h, sample-only) and engine
`pid 947557` (~95 min this life) still up. Hour **496552** closed at
17:00Z. Live hour **496553** is Kudu-only (engine FDW INSERT).

## Proven (no fake rows)

- Closed-hour analog from **FDW Kudu** (engine writer): **20430** rows →
  `gpu_metrics_hour_496552.h5` (201807 B) on analog + Iceberg data
  prefixes. Jsonl for that hour is **21594** rows (3599 ticks) — short
  **194** warehouse ticks (DCGM vs jsonl). Analog used warehouse rows,
  not padded jsonl. Polarisfork `FileFormat.HDF5`. HS2/FDW
  `gpu_metrics_tier1` GROUP BY includes **20430** for 496552. Sample
  `power_w=127` `util=100` `mem=21331` (real DCGM).
- **DROP RANGE VALUE = 496552** verified (catalog reload fault; SHOW
  RANGE left `496553` … `496569`). UNION no longer double-counts
  (was 40860 = 20430×2 before DROP):

  | hour   | store   | count |
  |--------|---------|-------|
  | 496550 | Iceberg | 20334 |
  | 496551 | Iceberg | 20460 |
  | 496552 | Iceberg | 20430 |
  | 496553 | Kudu    | live  |

- Live lag ~0.1 s. Sample `power_w=111/125` `mem=21333`. Strip=1h UI
  `driver=warehouse`, `n_times=3600`, matrix **72000**. gpu-0..5
  nonzero 3387/3600.

Live `gpu_metrics` VIEW is still `tier0 UNION ALL tier1` **without**
`NOT IN`. Honest after DROP; analog-before-DROP next hour will
double-count until DROP or the view lands.

## Next

Analog **496553** after 18:00Z close. Retry `ALTER VIEW … NOT IN` when
HMS accepts `alter_table`. Do not analog the open hour.
