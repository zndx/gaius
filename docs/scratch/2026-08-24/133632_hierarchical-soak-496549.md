# Hierarchical soak tick (13:36Z)

Sampler still C++ (`pid 2989721`, ~9.4 h, `kudu_ok`). Hour **496549**
hot (~36 min jsonl). Impala FE already `IMPALA_BUILD_OK`. Do not analog
— not closed (14:00Z). Hour **496548** already Iceberg.

## Proven (no fake rows)

- Live C++ upsert of jsonl hour 496549: **12924** rows (2154 ticks).
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
  | 496543 | Iceberg | 21600 |
  | 496544 | Iceberg | 21594 |
  | 496545 | Iceberg | 21600 |
  | 496546 | Iceberg | 21594 |
  | 496547 | Iceberg | 21600 |
  | 496548 | Iceberg | 21600 |
  | 496549 | Kudu    | 12996 |

  Analog hours match jsonl ticks×6. Kudu holds **only** 496549. UNION
  lag ~13 s after upsert. Sampler kept writing after the C++ upsert,
  so FDW is ahead of the 12924 snapshot.
- Strip=1h CLI+UI `driver=warehouse`, `n_times=3600`, matrix 72000.

## Next

Analog 496549 after 14:00Z close. Ranges 496549–565 already present.
Static `/tmp/gpu_kudu_create` still 01:57Z.
