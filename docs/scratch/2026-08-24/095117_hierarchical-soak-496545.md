# Hierarchical soak tick (09:51Z)

Sampler still C++ (`pid 2989721`, ~5.6 h, `kudu_ok`). Hour **496545**
hot (~51 min jsonl). Impala FE already `IMPALA_BUILD_OK`. Do not analog
— not closed (10:00Z).

## Proven (no fake rows)

- Live C++ upsert of jsonl hour 496545: **18264** rows (3044 ticks).
  Sample `power_w=107` `util=100` `mem=21334` (real nvidia-smi).
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
  | 496545 | Kudu    | 18264 |

  Analog hours match jsonl ticks×6. Kudu holds **only** 496545. UNION
  lag ~13 s after HS2 GROUP BY (upsert matched jsonl last ts).
- Strip=1h CLI+UI `driver=warehouse`, `n_times=3600`, matrix 72000.

## Next

Analog 496545 after 10:00Z close. Ranges 496545–549 already present.
Static `/tmp/gpu_kudu_create` still 01:57Z.
