# Hierarchical soak tick (22:21Z)

Hour **496558** still hot (~20 min). Below analog threshold (≥55 min /
23:00Z close). Impala FE already `IMPALA_BUILD_OK`. Do not analog.
Hour **496557** already Iceberg (20532).

## Sampler / engine

Jsonl sidecar `pid 36619` (~8.4 h, sample-only) still up. Engine
`pid 4115269` (started 21:16:19 this life) still up. Warehouse ingest
`ticks=3690 inserted=22140` by 22:20:27. Lag ~0–0.4 s. Live sample
`power_w=113–128` `util=100` `mem=21435` on GPUs 0/2/3, gpu-5 `mem=3`
(real DCGM). Jsonl 1242 ticks / 7452 rows vs Kudu **7356** rows
(1226 s) — short **~16** warehouse ticks from the 22:07 analog/DROP
catalog stall, not padded.

## Proven (no fake rows)

- `SHOW RANGE` starts at `VALUE = 496558` … `496582`. UNION honest:

  | hour   | store   | count |
  |--------|---------|-------|
  | 496554 | Iceberg | 13974 |
  | 496555 | Iceberg | 12486 |
  | 496556 | Iceberg | 16164 |
  | 496557 | Iceberg | 20532 |
  | 496558 | Kudu    | 7356 live |

- Strip=1h UI+CLI `driver=warehouse`, `n_times=3600`, matrix **72000**,
  epoch 22:21:01Z. gpu-0..5 nonzero 3475/3600 (honest recycle gaps).

## Next

Analog **496558** after 23:00Z close, then DROP RANGE 496558. Retry
`ALTER VIEW … NOT IN` when HMS accepts `alter_table`. Do not analog
the open hour. Keep sampler 36619 and engine ingest.
