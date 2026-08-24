# Hierarchical soak tick (08:36Z)

Sampler still C++ (`pid 2989721`, ~4.4 h, `kudu_ok`). Hour **496544**
hot (~36 min jsonl). Impala FE already `IMPALA_BUILD_OK`. Do not analog
— not closed (09:00Z).

## Proven (no fake rows)

- Live C++ upsert of jsonl hour 496544: **12996** rows (2166 ticks).
  Sample `power_w=48` `util=0` `mem=21334` (real nvidia-smi).
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
  | 496544 | Kudu    | 12996 |

  Analog hours match jsonl ticks×6. Kudu holds **only** 496544. UNION
  lag ~0.9 s after upsert.
- Strip=1h CLI+UI `driver=warehouse`, `n_times=3600`, matrix 72000.

## Next

Analog 496544 after 09:00Z close. Ranges 496544–546 already present.
Static `/tmp/gpu_kudu_create` still 01:57Z.
