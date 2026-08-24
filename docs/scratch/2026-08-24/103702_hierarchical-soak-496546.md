# Hierarchical soak tick (10:37Z)

Sampler still C++ (`pid 2989721`, ~6.4 h, `kudu_ok`). Hour **496546**
hot (~36 min jsonl). Impala FE already `IMPALA_BUILD_OK`. Do not analog
— not closed (11:00Z). Hour **496545** already Iceberg.

## Proven (no fake rows)

- Live C++ upsert of jsonl hour 496546: **12918** rows (2153 ticks).
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
  | 496545 | Iceberg | 21600 |
  | 496546 | Kudu    | 12978 |

  Analog hours match jsonl ticks×6. Kudu holds **only** 496546. UNION
  lag ~3.6 s after HS2 GROUP BY.
- Strip=1h CLI+UI `driver=warehouse`, `n_times=3600`, matrix 72000.

## Next

Analog 496546 after 11:00Z close. Ranges 496546–553 already present.
Static `/tmp/gpu_kudu_create` still 01:57Z.
