# Hierarchical soak: analog 496542 (07:04Z)

Sampler still C++ (`pid 2989721`, ~2.8 h, `kudu_ok`). Hour **496542**
closed at 07:00Z (3600 jsonl ticks). Live hour **496543** is Kudu-only.

## Proven (no fake rows)

- Closed-hour analog: 21600 jsonl rows →
  `gpu_metrics_hour_496542.h5` (212727 B) on analog + Iceberg data
  prefixes. Polarisfork append `FileFormat.HDF5`. HS2
  `gpu_metrics_tier1` GROUP BY = 12156+21930+21594+19968+21594+**21600**.
  Sample `power_w=110` `util=100` `mem=21334` (real nvidia-smi).
- Dropped Kudu range **496542** (ALTER reported TTransportException;
  SHOW RANGE left 496543–546). UNION no longer double-counts:

  | hour   | store   | count |
  |--------|---------|-------|
  | 496537 | Iceberg | 12156 |
  | 496538 | Iceberg | 21930 |
  | 496539 | Iceberg | 21594 |
  | 496540 | Iceberg | 19968 |
  | 496541 | Iceberg | 21594 |
  | 496542 | Iceberg | 21600 |
  | 496543 | Kudu    | live  |

- FDW `:5455` `gpu_metrics` `impala_sql`: analog hours exact + live
  496543 (lag ~19 s). Strip=1h CLI+UI `driver=warehouse`, `n_times=3600`,
  matrix 72000 (Iceberg 496542 + Kudu 496543). No engine/UI restart.
- HS2 `ADD RANGE` 496543–546 before the hour roll (static
  `/tmp/gpu_kudu_create` still 01:57Z and does not add ranges).

## Next

Analog 496543 after 08:00Z close. Rebuild `gpu_kudu_create` so the
sidecar adds the next hour without HS2 ALTER.
