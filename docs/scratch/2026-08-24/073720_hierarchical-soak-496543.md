# Hierarchical soak tick (07:37Z)

Sampler still C++ (`pid 2989721`, ~3.4 h, `kudu_ok`). Hour **496543**
hot (~37 min jsonl). Impala FE already `IMPALA_BUILD_OK`. Do not analog
— not closed (08:00Z).

## Proven (no fake rows)

- Live C++ upsert of jsonl hour 496543: **13020** rows (2170 ticks),
  then sampler continued. After removing one accidental ingest-probe
  PK (`power_w=1`), FDW `min_w=6.62` (real nvidia-smi). Sample
  `power_w=113` `util=100` `mem=21334`.
- FDW UNION `:5455` `gpu_metrics` `impala_sql`:

  | hour   | store   | count |
  |--------|---------|-------|
  | 496537 | Iceberg | 12156 |
  | 496538 | Iceberg | 21930 |
  | 496539 | Iceberg | 21594 |
  | 496540 | Iceberg | 19968 |
  | 496541 | Iceberg | 21594 |
  | 496542 | Iceberg | 21600 |
  | 496543 | Kudu    | 13332 |

  Analog hours match jsonl ticks×6. Kudu holds **only** 496543.
- Strip=1h CLI+UI `driver=warehouse`, `n_times=3600`, matrix 72000.

## Next

Analog 496543 after 08:00Z close. Ranges 496543–546 already present.
Static `/tmp/gpu_kudu_create` still 01:57Z.
