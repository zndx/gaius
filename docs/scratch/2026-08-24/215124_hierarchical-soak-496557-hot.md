# Hierarchical soak tick (21:51Z)

Hour **496557** still hot (~51 min). Below analog threshold (≥55 min /
22:00Z close). Impala FE already `IMPALA_BUILD_OK`. Do not analog.
Hour **496556** already Iceberg (16164).

## Sampler / engine

Jsonl sidecar `pid 36619` (~8.0 h, sample-only) still up. Engine
`pid 4115269` (started 21:16:19 this life) still up. Warehouse ingest
`ticks=1950 inserted=11700` by 21:50:38. Lag ~0–0.8 s. Live sample
`power_w=100–126` `util=100` `mem=21435` on GPUs 1–3, gpu-0 util 26,
gpu-5 `mem=3` (real DCGM). Jsonl 3053 ticks / 18318 rows vs Kudu
**17478** rows (2913 s) — short **~140** warehouse ticks from the
21:16 recycle stall, not padded.

## Proven (no fake rows)

- `SHOW RANGE` starts at `VALUE = 496557` … `496582`. UNION honest:

  | hour   | store   | count |
  |--------|---------|-------|
  | 496553 | Iceberg | 16770 |
  | 496554 | Iceberg | 13974 |
  | 496555 | Iceberg | 12486 |
  | 496556 | Iceberg | 16164 |
  | 496557 | Kudu    | 17478 live |

- Strip=1h UI+CLI `driver=warehouse`, `n_times=3600`, matrix **72000**,
  epoch 21:51:18Z. gpu-0..5 nonzero 3418/3600 (honest recycle gaps).

## Next

Analog **496557** after 22:00Z close, then DROP RANGE 496557. Retry
`ALTER VIEW … NOT IN` when HMS accepts `alter_table`. Do not analog
the open hour. Keep sampler 36619 and engine ingest.
