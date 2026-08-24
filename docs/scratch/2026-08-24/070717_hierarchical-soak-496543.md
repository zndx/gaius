# Hierarchical soak tick (07:07Z)

Sampler still C++ (`pid 2989721`, ~2.9 h, `kudu_ok`). Hour **496543**
hot (~7 min jsonl). Impala FE already `IMPALA_BUILD_OK`; no rebuild
running. Do not analog — not ≥55 min / not closed.

## Proven (no fake rows)

- Live C++ upsert of jsonl hour 496543: **2382** rows (397 ticks).
  Sampler continues 30-tick batches. Sample `power_w=110` `util=100`
  `mem=21334` (real nvidia-smi).
- FDW UNION `:5455` `gpu_metrics` `impala_sql`:

  | hour   | store   | count |
  |--------|---------|-------|
  | 496537 | Iceberg | 12156 |
  | 496538 | Iceberg | 21930 |
  | 496539 | Iceberg | 21594 |
  | 496540 | Iceberg | 19968 |
  | 496541 | Iceberg | 21594 |
  | 496542 | Iceberg | 21600 |
  | 496543 | Kudu    | 2382  |

  Analog hours match jsonl ticks×6 exactly. Kudu `gpu_metrics_tier0`
  holds **only** 496543. UNION lag ~1 s after upsert. Ranges 496543–546.
- Strip=1h CLI+UI `driver=warehouse`, `n_times=3600`, `n_channels=20`,
  matrix 72000. No engine/UI restart.

## Next

Analog 496543 after 08:00Z close. Static `/tmp/gpu_kudu_create` still
01:57Z (no `AddRangePartition` in `main`); HS2 already added 496543–546.
Rebuild still needs the full proto/glog `.a` group (`libsasl2.so.3` is
fine on the 01:57 binary).
