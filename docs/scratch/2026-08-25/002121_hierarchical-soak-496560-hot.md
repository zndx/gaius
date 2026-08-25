# Hierarchical soak tick (00:21Z)

Hour **496560** still hot (~21 min). Below analog threshold (≥55 min /
01:00Z close). Impala FE already `IMPALA_BUILD_OK`. Do not analog.
Hour **496559** already Iceberg (21030). DROP RANGE 496559 already
verified last tick.

## Sampler / engine

Jsonl sidecar `pid 36619` (~10.5 h, sample-only) still up. Engine
`pid 4115269` (started 21:16:19 this life) still up. Warehouse ingest
`ticks=10710 inserted=64260` by 00:20:36. Lag ~0.1 s. Live sample
`power_w=119/120/132` `util=100` `mem=21435` on GPUs 0–2, gpu-5
`mem=3` (real DCGM). Jsonl 1257 ticks / 7542 rows vs Kudu **7302**
rows (1217 s) — short **~40** warehouse ticks from the 00:09 analog
and DROP catalog stall, not padded.

## Proven (no fake rows)

- `SHOW RANGE` starts at `VALUE = 496560` … `496582`. UNION honest:

  | hour   | store   | count |
  |--------|---------|-------|
  | 496556 | Iceberg | 16164 |
  | 496557 | Iceberg | 20532 |
  | 496558 | Iceberg | 21036 |
  | 496559 | Iceberg | 21030 |
  | 496560 | Kudu    | 7302 live |

- Strip=1h UI+CLI `driver=warehouse`, `n_times=3600`, matrix **72000**,
  epoch 00:21:16Z. gpu-0..5 nonzero 3502/3600 (honest recycle gaps).

## Next

Analog **496560** after 01:00Z close, then DROP RANGE 496560. Retry
`ALTER VIEW … NOT IN` when HMS accepts `alter_table`. Do not analog
the open hour. Keep sampler 36619 and engine ingest.
