# Hierarchical soak tick (01:36Z)

Hour **496561** still hot (~36 min). Below analog threshold (≥55 min /
02:00Z close). Impala FE already `IMPALA_BUILD_OK`. Do not analog.
Hour **496560** already Iceberg (21048). DROP RANGE 496560 already
verified. Settle clock (`gpu-metrics-settle` pg_cron at `:05`) did
not analog the open hour.

## Sampler / engine

Jsonl sidecar `pid 36619` (~11.7 h, sample-only) still up. Engine
`pid 4115269` (started 21:16:19 this life) still up. Warehouse ingest
`ticks=15120 inserted=90720` by 01:36:03. Lag ~0.3 s. Live sample
`power_w=105/126/137/137` `util=100` `mem=21435` on GPUs 1–3, gpu-5
`mem=3` (real DCGM). Jsonl 2183 ticks / 13098 rows vs Kudu **12702**
rows (2117 s) — short **~66** warehouse ticks from the 01:07 analog
and DROP catalog stall, not padded.

## Proven (no fake rows)

- `SHOW RANGE` starts at `VALUE = 496561` … `496582`. UNION honest:

  | hour   | store   | count |
  |--------|---------|-------|
  | 496557 | Iceberg | 20532 |
  | 496558 | Iceberg | 21036 |
  | 496559 | Iceberg | 21030 |
  | 496560 | Iceberg | 21048 |
  | 496561 | Kudu    | 12702 live |

- Strip=1h UI+CLI `driver=warehouse`, `n_times=3600`, matrix **72000**,
  epoch 01:36:50Z. gpu-0..5 nonzero 3503/3600 (honest recycle gaps).

## Next

Analog **496561** after 02:00Z close, then DROP RANGE 496561 (soak or
`gpu-metrics-settle` at 02:05Z). Retry `ALTER VIEW … NOT IN` when HMS
accepts `alter_table`. Do not analog the open hour. Keep sampler 36619
and engine ingest.
