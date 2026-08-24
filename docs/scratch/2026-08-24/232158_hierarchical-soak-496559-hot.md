# Hierarchical soak tick (23:21Z)

Hour **496559** still hot (~21 min). Below analog threshold (≥55 min /
00:00Z close). Impala FE already `IMPALA_BUILD_OK`. Do not analog.
Hour **496558** already Iceberg (21036).

**DROP RANGE VALUE = 496558** applied this tick (was blocked at 23:07Z
analog). SHOW RANGE left `496559` … `496582`. UNION no longer
double-counts (was 42072 = 21036×2).

## Sampler / engine

Jsonl sidecar `pid 36619` (~9.5 h, sample-only) still up. Engine
`pid 4115269` (started 21:16:19 this life) still up. Warehouse ingest
`ticks=7260 inserted=43560` by 23:21:32. Lag ~0.9 s. Live sample
`power_w=107–132` `util=100` `mem=21435` on GPUs 1–3, gpu-5 `mem=3`
(real DCGM). Jsonl 1319 ticks / 7914 rows vs Kudu **7656** rows
(1276 s) — short **~43** warehouse ticks from the DROP catalog stall,
not padded.

## Proven (no fake rows)

- `SHOW RANGE` starts at `VALUE = 496559` … `496582`. UNION honest:

  | hour   | store   | count |
  |--------|---------|-------|
  | 496555 | Iceberg | 12486 |
  | 496556 | Iceberg | 16164 |
  | 496557 | Iceberg | 20532 |
  | 496558 | Iceberg | 21036 |
  | 496559 | Kudu    | 7656 live |

- Strip=1h UI+CLI `driver=warehouse`, `n_times=3600`, matrix **72000**,
  epoch 23:21:52Z. gpu-0..5 nonzero 3503/3600 (honest recycle gaps).

## Next

Analog **496559** after 00:00Z close, then DROP RANGE 496559. Retry
`ALTER VIEW … NOT IN` when HMS accepts `alter_table`. Do not analog
the open hour. Keep sampler 36619 and engine ingest.
