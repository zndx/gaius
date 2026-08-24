# Hierarchical soak tick (11:56Z)

Sampler still C++ (`pid 2989721`, ~7.7 h, `kudu_ok`). Hour **496547**
hot (~56 min jsonl). Impala FE already `IMPALA_BUILD_OK`. Do not analog
— not closed (12:00Z). Hour **496546** already Iceberg.

## Proven (no fake rows)

- Live C++ upsert of jsonl hour 496547: **19404** rows (3234 ticks).
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
  | 496546 | Iceberg | 21594 |
  | 496547 | Kudu    | 20010 |

  Analog hours match jsonl ticks×6. Kudu holds **only** 496547
  (ranges 496547–557). UNION lag ~7 s after upsert. Sampler kept
  writing after the C++ upsert, so FDW is ahead of the 19404 snapshot.
- Strip=1h CLI+UI `driver=warehouse`, `n_times=3600`, matrix 72000.

## Next

Analog 496547 after 12:00Z close. Ranges 496547–557 already present.
Static `/tmp/gpu_kudu_create` still 01:57Z.
