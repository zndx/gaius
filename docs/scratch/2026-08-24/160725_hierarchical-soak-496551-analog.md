# Hierarchical soak: analog 496551 (16:07Z)

Jsonl sampler `pid 36619` (~2.2 h, sample-only) and engine
`pid 947557` (~35 min this life) still up. Hour **496551** closed at
16:00Z. Live hour **496552** is Kudu-only (engine FDW INSERT).

## Proven (no fake rows)

- Closed-hour analog from **FDW Kudu** (engine writer): **20460** rows →
  `gpu_metrics_hour_496551.h5` (202087 B) on analog + Iceberg data
  prefixes. Jsonl for that hour is **21582** rows (3597 ticks) — short
  **187** warehouse ticks for the 15:32 engine restart hole plus DCGM
  vs jsonl 1 s mismatches. Analog used warehouse rows, not padded jsonl.
  Polarisfork `FileFormat.HDF5`. HS2/FDW `gpu_metrics_tier1` GROUP BY
  includes **20460** for 496551. Sample `power_w=127` `util=100`
  `mem=21225` (real DCGM).
- **DROP RANGE VALUE = 496551** verified (catalog reload fault; SHOW
  RANGE left `496552` … `496569`). UNION no longer double-counts
  (was 40920 = 20460×2 before DROP):

  | hour   | store   | count |
  |--------|---------|-------|
  | 496549 | Iceberg | 19752 |
  | 496550 | Iceberg | 20334 |
  | 496551 | Iceberg | 20460 |
  | 496552 | Kudu    | live  |

- Live lag ~0.1 s. Sample `power_w=94/126` `mem=21331`. Strip=1h UI
  `driver=warehouse`, `n_times=3600`, matrix **72000**. gpu-0..5
  nonzero 3429/3600.

Live `gpu_metrics` VIEW is still `tier0 UNION ALL tier1` **without**
`NOT IN`. Honest after DROP; analog-before-DROP next hour will
double-count until DROP or the view lands.

## Next

Analog **496552** after 17:00Z close. Retry `ALTER VIEW … NOT IN` when
HMS accepts `alter_table`. Do not analog the open hour.
