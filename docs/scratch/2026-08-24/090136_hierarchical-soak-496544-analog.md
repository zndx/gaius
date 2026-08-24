# Hierarchical soak: analog 496544 (09:01Z)

Sampler still C++ (`pid 2989721`, ~4.8 h, `kudu_ok`). Hour **496544**
closed at 09:00Z (3599 jsonl ticks). Live hour **496545** is Kudu-only.

## Proven (no fake rows)

- Closed-hour analog: 21594 jsonl rows →
  `gpu_metrics_hour_496544.h5` (212671 B) on analog + Iceberg data
  prefixes. Polarisfork append `FileFormat.HDF5`. HS2
  `gpu_metrics_tier1` GROUP BY =
  12156+21930+21594+19968+21594+21600+21600+**21594**. Sample
  `power_w=109` `util=100` `mem=21334` (real nvidia-smi).
- Dropped Kudu range **496544** (ALTER reported TTransportException;
  SHOW RANGE left 496545–549 after ADD 547–549). UNION no longer
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
  | 496545 | Kudu    | live  |

- FDW `:5455` `gpu_metrics` `impala_sql`: analog hours exact + live
  496545 (lag ~22 s). Strip=1h CLI+UI `driver=warehouse`, `n_times=3600`,
  matrix 72000. No engine/UI restart.

## Next

Analog 496545 after 10:00Z close. Static `/tmp/gpu_kudu_create` still
01:57Z; ranges 496545–549 already present.
