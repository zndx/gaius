# Hierarchical soak: analog 496543 (08:01Z)

Sampler still C++ (`pid 2989721`, ~3.8 h, `kudu_ok`). Hour **496543**
closed at 08:00Z (3600 jsonl ticks). Live hour **496544** is Kudu-only.

## Proven (no fake rows)

- Closed-hour analog: 21600 jsonl rows →
  `gpu_metrics_hour_496543.h5` (212727 B) on analog + Iceberg data
  prefixes. Polarisfork append `FileFormat.HDF5`. HS2
  `gpu_metrics_tier1` GROUP BY =
  12156+21930+21594+19968+21594+21600+**21600**. Sample `power_w=109`
  `util=100` `mem=21334` (real nvidia-smi).
- Dropped Kudu range **496543** (ALTER reported TTransportException;
  SHOW RANGE left 496544–546). UNION no longer double-counts:

  | hour   | store   | count |
  |--------|---------|-------|
  | 496537 | Iceberg | 12156 |
  | 496538 | Iceberg | 21930 |
  | 496539 | Iceberg | 21594 |
  | 496540 | Iceberg | 19968 |
  | 496541 | Iceberg | 21594 |
  | 496542 | Iceberg | 21600 |
  | 496543 | Iceberg | 21600 |
  | 496544 | Kudu    | live  |

- FDW `:5455` `gpu_metrics` `impala_sql`: analog hours exact + live
  496544 (lag ~11 s). Strip=1h CLI+UI `driver=warehouse`, `n_times=3600`,
  matrix 72000. No engine/UI restart.

## Next

Analog 496544 after 09:00Z close. Static `/tmp/gpu_kudu_create` still
01:57Z; ranges 496544–546 already present.
