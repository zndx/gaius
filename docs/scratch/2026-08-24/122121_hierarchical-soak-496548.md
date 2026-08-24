# Hierarchical soak tick (12:21Z)

Sampler still C++ (`pid 2989721`, ~8.1 h, `kudu_ok`). Hour **496548**
hot (~21 min jsonl). Impala FE already `IMPALA_BUILD_OK`. Do not analog
— not closed (13:00Z). Hour **496547** already Iceberg.

## Proven (no fake rows)

- Live C++ upsert of jsonl hour 496548: **7506** rows (1251 ticks).
  Sample `power_w=48.7` `util=0` `mem=21334` (real nvidia-smi; GPUs
  idle this tick).
- FDW UNION `:5455` `gpu_metrics` `impala_sql`:

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
  | 496547 | Iceberg | 21600 |
  | 496548 | Kudu    | 7590  |

  Analog hours match jsonl ticks×6. Kudu holds **only** 496548. UNION
  lag ~3.3 s after upsert. Sampler kept writing after the C++ upsert,
  so FDW is ahead of the 7506 snapshot.
- Strip=1h CLI+UI `driver=warehouse`, `n_times=3600`, matrix 72000.

## Next

Analog 496548 after 13:00Z close. Ranges 496548–561 already present.
Static `/tmp/gpu_kudu_create` still 01:57Z.
