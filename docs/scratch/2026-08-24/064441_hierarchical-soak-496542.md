# Hierarchical soak tick (06:44Z)

Sampler still C++ (`pid 2989721`, ~2.5 h, `kudu_ok`). Hour **496542**
hot (~45 min jsonl). Impala FE already `IMPALA_BUILD_OK`; no rebuild
running. Do not analog — not ≥55 min / not closed.

## Proven (no fake rows)

- Live C++ upsert of jsonl hour 496542: **14562** rows at 06:40Z
  (2427 ticks). Sampler continues 30-tick batches.
- FDW UNION `:5455` `gpu_metrics` `impala_sql`:

  | hour   | store   | count |
  |--------|---------|-------|
  | 496537 | Iceberg | 12156 |
  | 496538 | Iceberg | 21930 |
  | 496539 | Iceberg | 21594 |
  | 496540 | Iceberg | 19968 |
  | 496541 | Iceberg | 21594 |
  | 496542 | Kudu    | 16032 |

  Analog hours match jsonl ticks×6 exactly. Kudu `gpu_metrics_tier0`
  holds **only** 496542. UNION and `kudu_scan` max(ts) agree (lag is
  the C++ 30-tick flush, ~25 s).
- Strip=1h CLI+UI `driver=warehouse`, `n_times=3600`, `n_channels=20`,
  matrix 72000 (nonzero ~32k). No engine/UI restart.

## Next

Analog 496542 after 07:00Z, Polarisfork HDF5, Iceberg GROUP BY, then
DROP Kudu range 496542. Sidecar HS2 python still `No module named
'impala'` / venv missing GSSAPI; C++ ingest + FDW are enough.
Static `/tmp/gpu_kudu_create` still 01:57Z.
