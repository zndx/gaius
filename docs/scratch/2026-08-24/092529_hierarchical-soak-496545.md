# Hierarchical soak tick (09:25Z)

Sampler still C++ (`pid 2989721`, ~5.2 h, `kudu_ok`). Hour **496545**
hot (~25 min jsonl). Impala FE already `IMPALA_BUILD_OK`. Do not analog
— not closed (10:00Z).

## Proven (no fake rows)

- Live C++ upsert of jsonl hour 496545: **9030** rows (1505 ticks).
  Sample `power_w=109` `util=100` `mem=21334` (real nvidia-smi).
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
  | 496545 | Kudu    | 9030  |

  Analog hours match jsonl ticks×6. Kudu holds **only** 496545. UNION
  lag ~1.7 s after upsert.
- Strip=1h CLI+UI `driver=warehouse`, `n_times=3600`, matrix 72000.

## Next

Analog 496545 after 10:00Z close. Ranges 496545–549 already present.
Static `/tmp/gpu_kudu_create` still 01:57Z.
