# Hierarchical soak tick (22:36Z)

Hour **496558** still hot (~36 min). Below analog threshold (≥55 min /
23:00Z close). Impala FE already `IMPALA_BUILD_OK`. Do not analog.
Hour **496557** already Iceberg (20532).

## Sampler / engine

Jsonl sidecar `pid 36619` (~8.7 h, sample-only) still up. Engine
`pid 4115269` (started 21:16:19 this life) still up. Warehouse ingest
`ticks=4590 inserted=27540` by 22:35:52. Lag ~0.6 s. Live sample
`power_w=112–130` `util=100` `mem=21435` on GPUs 2–3, gpu-5 `mem=3`
(real DCGM). Jsonl 2166 ticks / 12996 rows vs Kudu **12750** rows
(2125 s) — short **~41** warehouse ticks from the 22:07 analog/DROP
catalog stall, not padded.

## Proven (no fake rows)

- `SHOW RANGE` starts at `VALUE = 496558` … `496582`. UNION honest:

  | hour   | store   | count |
  |--------|---------|-------|
  | 496554 | Iceberg | 13974 |
  | 496555 | Iceberg | 12486 |
  | 496556 | Iceberg | 16164 |
  | 496557 | Iceberg | 20532 |
  | 496558 | Kudu    | 12750 live |

- Strip=1h UI+CLI `driver=warehouse`, `n_times=3600`, matrix **72000**,
  epoch 22:36:26Z. gpu-0..5 nonzero 3501/3600 (honest recycle gaps).

## Next

Analog **496558** after 23:00Z close, then DROP RANGE 496558. Retry
`ALTER VIEW … NOT IN` when HMS accepts `alter_table`. Do not analog
the open hour. Keep sampler 36619 and engine ingest.
