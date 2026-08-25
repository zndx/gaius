# Hierarchical soak tick (00:36Z)

Hour **496560** still hot (~36 min). Below analog threshold (≥55 min /
01:00Z close). Impala FE already `IMPALA_BUILD_OK`. Do not analog.
Hour **496559** already Iceberg (21030). DROP RANGE 496559 already
verified.

## Sampler / engine

Jsonl sidecar `pid 36619` (~10.7 h, sample-only) still up. Engine
`pid 4115269` (started 21:16:19 this life) still up. Warehouse ingest
`ticks=11580 inserted=69480` by 00:35:28. Lag ~0 s. Live sample
`power_w=121/123/136` `util=100` `mem=21435` on GPUs 0/1/3, gpu-5
`mem=3` (real DCGM). Jsonl 2156 ticks / 12936 rows vs Kudu **12558**
rows (2093 s) — short **~63** warehouse ticks from the 00:09 analog
and DROP catalog stall, not padded.

## Proven (no fake rows)

- `SHOW RANGE` starts at `VALUE = 496560` … `496582`. UNION honest:

  | hour   | store   | count |
  |--------|---------|-------|
  | 496556 | Iceberg | 16164 |
  | 496557 | Iceberg | 20532 |
  | 496558 | Iceberg | 21036 |
  | 496559 | Iceberg | 21030 |
  | 496560 | Kudu    | 12558 live |

- Strip=1h UI+CLI `driver=warehouse`, `n_times=3600`, matrix **72000**,
  epoch 00:36:19Z. gpu-0..5 nonzero 3504/3600 (honest recycle gaps).

## Next

Analog **496560** after 01:00Z close, then DROP RANGE 496560. Retry
`ALTER VIEW … NOT IN` when HMS accepts `alter_table`. Do not analog
the open hour. Keep sampler 36619 and engine ingest.
