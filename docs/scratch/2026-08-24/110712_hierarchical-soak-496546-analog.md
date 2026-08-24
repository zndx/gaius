# Hierarchical soak: analog 496546 (11:07Z)

Sampler still C++ (`pid 2989721`, ~6.9 h, `kudu_ok`). Hour **496546**
closed at 11:00Z (3599 jsonl ticks). Live hour **496547** is Kudu-only.

## Proven (no fake rows)

- Closed-hour analog: 21594 jsonl rows →
  `gpu_metrics_hour_496546.h5` (212671 B) on analog + Iceberg data
  prefixes. Polarisfork append `FileFormat.HDF5`. HS2
  `gpu_metrics_tier1` GROUP BY =
  12156+21930+21594+19968+21594+21600+21600+21594+21600+**21594**. Sample
  `power_w=108` `util=100` `mem=21334` (real nvidia-smi).
- Dropped Kudu range **496546** (ALTER reported TTransportException;
  SHOW RANGE left 496547–557 after ADD 554–557). UNION no longer
  double-counts:

  | hour   | store   | count |
  |--------|---------|-------|
  | 496537 | Iceberg | 12156 |
  | 496538 | Iceberg | 21930 |
  | 496539 | Iceberg | 21594 |
  | 496540 | Iceberg | 19968 |
  | 496541 | Iceberg | 21594 |
  | 496542 | Iceberg | 21600 |
  | 496543 | Iceberg | 21600 |
  | 496544 | Iceberg | 21594 |
  | 496545 | Iceberg | 21600 |
  | 496546 | Iceberg | 21594 |
  | 496547 | Kudu    | live  |

- FDW `:5455` `gpu_metrics` `impala_sql`: analog hours exact + live
  496547. Strip=1h CLI+UI `driver=warehouse`, `n_times=3600`,
  matrix 72000. No engine/UI restart.

## Next

Analog 496547 after 12:00Z close. Static `/tmp/gpu_kudu_create` still
01:57Z; ranges 496547–557 already present.
