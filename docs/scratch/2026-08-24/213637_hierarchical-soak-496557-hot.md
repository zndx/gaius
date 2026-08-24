# Hierarchical soak tick (21:36Z)

Hour **496557** still hot (~36 min). Below analog threshold (≥55 min /
22:00Z close). Impala FE already `IMPALA_BUILD_OK`. Do not analog.
Hour **496556** already Iceberg (16164).

## Sampler / engine

Jsonl sidecar `pid 36619` (~7.7 h, sample-only) still up. Engine
`pid 4115269` (started 21:16:19 this life) still up. Warehouse ingest
`ticks=1110 inserted=6660` by 21:36:16. Lag ~0.1–0.4 s. Live sample
`power_w=110–129` `util=100` `mem=21435` on GPUs 1–3, gpu-0 util 24,
gpu-5 `mem=3` (real DCGM). Jsonl 2153 ticks / 12918 rows vs Kudu
**12300** rows (2050 s) — short **~103** warehouse ticks from the
21:16 recycle stall, not padded.

## Proven (no fake rows)

- `SHOW RANGE` starts at `VALUE = 496557` … `496582`. UNION honest:

  | hour   | store   | count |
  |--------|---------|-------|
  | 496553 | Iceberg | 16770 |
  | 496554 | Iceberg | 13974 |
  | 496555 | Iceberg | 12486 |
  | 496556 | Iceberg | 16164 |
  | 496557 | Kudu    | 12300 live |

- Strip=1h UI+CLI `driver=warehouse`, `n_times=3600`, matrix **72000**,
  epoch 21:36:20Z. gpu-0..5 nonzero 3315/3600 (honest recycle gaps).

## Next

Analog **496557** after 22:00Z close, then DROP RANGE 496557. Retry
`ALTER VIEW … NOT IN` when HMS accepts `alter_table`. Do not analog
the open hour. Keep sampler 36619 and engine ingest.
