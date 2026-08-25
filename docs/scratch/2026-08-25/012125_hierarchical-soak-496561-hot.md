# Hierarchical soak tick (01:21Z)

Hour **496561** still hot (~21 min). Below analog threshold (≥55 min /
02:00Z close). Impala FE already `IMPALA_BUILD_OK`. Do not analog.
Hour **496560** already Iceberg (21048). DROP RANGE 496560 already
verified last tick.

## Sampler / engine

Jsonl sidecar `pid 36619` (~11.5 h, sample-only) still up. Engine
`pid 4115269` (started 21:16:19 this life) still up. Warehouse ingest
`ticks=14220 inserted=85320` by 01:20:38. Lag ~0.9 s. Live sample
`power_w=118/123/135/136` `util=100` `mem=21435` on GPUs 1–3, gpu-5
`mem=3` (real DCGM). Jsonl 1260 ticks / 7560 rows vs Kudu **7314**
rows (1219 s) — short **~41** warehouse ticks from the 01:07 analog
and DROP catalog stall, not padded.

## Proven (no fake rows)

- `SHOW RANGE` starts at `VALUE = 496561` … `496582`. UNION honest:

  | hour   | store   | count |
  |--------|---------|-------|
  | 496557 | Iceberg | 20532 |
  | 496558 | Iceberg | 21036 |
  | 496559 | Iceberg | 21030 |
  | 496560 | Iceberg | 21048 |
  | 496561 | Kudu    | 7314 live |

- Strip=1h UI+CLI `driver=warehouse`, `n_times=3600`, matrix **72000**,
  epoch 01:21:20Z. gpu-0..5 nonzero 3505/3600 (honest recycle gaps).

## Next

Analog **496561** after 02:00Z close, then DROP RANGE 496561. Retry
`ALTER VIEW … NOT IN` when HMS accepts `alter_table`. Do not analog
the open hour. Keep sampler 36619 and engine ingest.
