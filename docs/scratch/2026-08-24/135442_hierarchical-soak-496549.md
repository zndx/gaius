# Hierarchical soak tick (13:54Z)

Hour **496549** still hot (~54 min). Impala FE already `IMPALA_BUILD_OK`.
Do not analog — not closed (14:00Z). Hour **496548** already Iceberg.

## Sampler

Sidecar `pid 2989721` died at 13:46:23Z (working-tree
`gpu_metrics_kudu_ingest.py` now `SystemExit` retired; Gaius engine
restarted 13:50Z). Honest jsonl gap **447.7 s**
(13:46:23 → 13:53:50). No fake rows.

Engine `warehouse_ingest` (`pid 8851`) writes Kudu at 1 Hz via Postgres
`:5455` `gpu_metrics_tier0` `kudu_scan` INSERT (`#EN.00000031`). Jsonl
resumed `pid 36619` (sample+append only — no C++ upsert, so it does not
double-count engine rows). `kudu_via=engine_fdw`.

HS2 `DELETE` removed one junk Kudu row
(`ts_ns=1787579999000000000`, `power_w=42` `util=1` `mem=100`) that
was not nvidia-smi.

## Proven (no fake rows)

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
  | 496549 | Kudu    | 17982 |

  Analog hours match jsonl ticks×6. Kudu holds **only** 496549 (sidecar
  13:00–13:46 + engine from 13:50; gap unfilled). UNION lag ~1.7 s.
  Sample `power_w=6.5` `util=0` `mem=21118` (real nvidia-smi; vLLM
  thinking loading GPUs 0–3).
- Strip=1h CLI+UI `driver=warehouse`, `n_times=3600`, matrix 72000.

## Next

Analog 496549 after 14:00Z close. Jsonl for that hour will be short by
the 447 s gap. Ranges 496549–565 already present.
