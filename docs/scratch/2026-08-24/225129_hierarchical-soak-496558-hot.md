# Hierarchical soak tick (22:51Z)

Hour **496558** still hot (~51 min). Below analog threshold (≥55 min /
23:00Z close). Impala FE already `IMPALA_BUILD_OK`. Do not analog.
Hour **496557** already Iceberg (20532).

## Sampler / engine

Jsonl sidecar `pid 36619` (~8.9 h, sample-only) still up. Engine
`pid 4115269` (started 21:16:19 this life) still up. Warehouse ingest
`ticks=5460 inserted=32760` by 22:50:44. Lag ~0.7 s. Live sample
`power_w=114–131` `util=100` `mem=21435` on GPUs 1–3, gpu-5 `mem=3`
(real DCGM). Jsonl 3065 ticks / 18390 rows vs Kudu **18012** rows
(3002 s) — short **~63** warehouse ticks from the 22:07 analog/DROP
catalog stall, not padded.

## Proven (no fake rows)

- `SHOW RANGE` starts at `VALUE = 496558` … `496582`. UNION honest:

  | hour   | store   | count |
  |--------|---------|-------|
  | 496554 | Iceberg | 13974 |
  | 496555 | Iceberg | 12486 |
  | 496556 | Iceberg | 16164 |
  | 496557 | Iceberg | 20532 |
  | 496558 | Kudu    | 18012 live |

- Strip=1h UI+CLI `driver=warehouse`, `n_times=3600`, matrix **72000**,
  epoch 22:51:25Z. gpu-0..5 nonzero 3503/3600 (honest recycle gaps).

## Next

Analog **496558** after 23:00Z close, then DROP RANGE 496558. Retry
`ALTER VIEW … NOT IN` when HMS accepts `alter_table`. Do not analog
the open hour. Keep sampler 36619 and engine ingest.
