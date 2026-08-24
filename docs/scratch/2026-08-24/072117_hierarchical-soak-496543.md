# Hierarchical soak tick (07:21Z)

Sampler still C++ (`pid 2989721`, ~3.1 h, `kudu_ok`). Hour **496543**
hot (~21 min jsonl). Impala FE already `IMPALA_BUILD_OK`. Do not analog
— not ≥55 min / not closed.

## Proven (no fake rows)

- Live C++ upsert of jsonl hour 496543: **7536** rows (1256 ticks).
  Sample `power_w=110` `util=100` `mem=21334` (real nvidia-smi).
- FDW UNION `:5455` `gpu_metrics` `impala_sql`:

  | hour   | store   | count |
  |--------|---------|-------|
  | 496537 | Iceberg | 12156 |
  | 496538 | Iceberg | 21930 |
  | 496539 | Iceberg | 21594 |
  | 496540 | Iceberg | 19968 |
  | 496541 | Iceberg | 21594 |
  | 496542 | Iceberg | 21600 |
  | 496543 | Kudu    | 7536  |

  Analog hours match jsonl ticks×6. Kudu holds **only** 496543. UNION
  lag ~1.4 s after upsert.
- Strip=1h CLI+UI `driver=warehouse`, `n_times=3600`, matrix 72000.

## Next

Analog 496543 after 08:00Z close. Static `/tmp/gpu_kudu_create` still
01:57Z; ranges 496543–546 already present.
