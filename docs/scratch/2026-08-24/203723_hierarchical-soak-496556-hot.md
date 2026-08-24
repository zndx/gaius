# Hierarchical soak tick (20:37Z)

Hour **496556** still hot (~37 min). Below analog threshold (≥55 min /
21:00Z close). Impala FE already `IMPALA_BUILD_OK`. Do not analog.
Hour **496555** already Iceberg (12486).

## Sampler / engine

Jsonl sidecar `pid 36619` (~6.7 h, sample-only) still up. Engine recycled
at **20:35:19** (`pid 3711380`); previous `pid 3518301` (20:12Z this
life) is gone. Warehouse ingest recovered: `ticks=90 inserted=540` by
20:37:10 (first tick 20:35:30). Lag ~0.2–0.7 s. Live sample
`power_w=5.4–18.5` `mem=3` (real DCGM after `gpu_cleanup`). Jsonl 2240
ticks / 13440 rows vs Kudu **8826** rows (1471 s) — short **~769**
warehouse ticks from earlier recycles plus this 20:35 restart, not
padded.

## Proven (no fake rows)

- `SHOW RANGE` starts at `VALUE = 496556` … `496578`. UNION honest:

  | hour   | store   | count |
  |--------|---------|-------|
  | 496553 | Iceberg | 16770 |
  | 496554 | Iceberg | 13974 |
  | 496555 | Iceberg | 12486 |
  | 496556 | Kudu    | 8826 live |

- Strip=1h UI+CLI `driver=warehouse`, `n_times=3600`, matrix **72000**,
  epoch 20:36:48Z. gpu-0..5 nonzero 2281/3600 (honest recycle/stall
  gaps).

## Next

Analog **496556** after 21:00Z close, then DROP RANGE 496556. Retry
`ALTER VIEW … NOT IN` when HMS accepts `alter_table`. Do not analog
the open hour. Keep sampler 36619 and engine ingest.
