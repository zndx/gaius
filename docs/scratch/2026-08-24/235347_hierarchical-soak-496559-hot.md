# Hierarchical soak tick (23:53Z)

Hour **496559** still hot (~53 min). Below analog threshold (≥55 min /
00:00Z close). Impala FE already `IMPALA_BUILD_OK`. Do not analog.
Hour **496558** already Iceberg (21036). DROP RANGE 496558 already
verified last tick.

## Sampler / engine

Jsonl sidecar `pid 36619` (~10.0 h, sample-only) still up. Engine
`pid 4115269` (started 21:16:19 this life) still up. Warehouse ingest
`ticks=9120 inserted=54720` by 23:53:21. Lag ~0 s. Live sample
`power_w=119/111/133/133` `util=100` `mem=21435` on GPUs 0/2/3, gpu-5
`mem=3` (real DCGM). Jsonl 3226 ticks / 19356 rows vs Kudu **18816**
rows (3136 s) — short **~90** warehouse ticks from the 23:07 analog
and 23:21 DROP catalog stalls, not padded.

## Proven (no fake rows)

- `SHOW RANGE` starts at `VALUE = 496559` … `496582`. UNION honest:

  | hour   | store   | count |
  |--------|---------|-------|
  | 496555 | Iceberg | 12486 |
  | 496556 | Iceberg | 16164 |
  | 496557 | Iceberg | 20532 |
  | 496558 | Iceberg | 21036 |
  | 496559 | Kudu    | 18816 live |

- Strip=1h UI+CLI `driver=warehouse`, `n_times=3600`, matrix **72000**,
  epoch 23:52:04Z. gpu-0..5 nonzero 3503/3600 (honest recycle gaps).

## Next

Analog **496559** after 00:00Z close, then DROP RANGE 496559. Retry
`ALTER VIEW … NOT IN` when HMS accepts `alter_table`. Do not analog
the open hour. Keep sampler 36619 and engine ingest.
