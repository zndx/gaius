# Hierarchical soak tick (19:36Z)

Hour **496555** still hot (~36 min). Below analog threshold (≥55 min /
20:00Z close). Impala FE already `IMPALA_BUILD_OK`. Do not analog.
Hour **496554** already Iceberg (13974).

## Sampler / engine

Jsonl sidecar `pid 36619` (~5.7 h, sample-only) still up. Engine recycled
at **19:28:33** (`pid 3143183`); previous `pid 3032675` is gone. Warehouse
ingest recovered: `ticks=360 inserted=2160` by 19:35:55. Lag ~0.6 s.
Live sample `power_w=76.5/83.0/84.4` `util=100` `mem=21325` on GPUs
1–3 (thinking), gpu-0 `mem=24060` idle watts, gpu-5 `mem=3` (real DCGM).
Jsonl 2167 ticks / 13002 rows vs Kudu **7116** rows (1186 s) — short
**~981** warehouse ticks from 19:00–19:10 engine-down plus 19:16 and
19:28 recycles, not padded.

## Proven (no fake rows)

- `SHOW RANGE` starts at `VALUE = 496555` … `496574`. UNION honest:

  | hour   | store   | count |
  |--------|---------|-------|
  | 496552 | Iceberg | 20430 |
  | 496553 | Iceberg | 16770 |
  | 496554 | Iceberg | 13974 |
  | 496555 | Kudu    | 7116 live |

- Strip=1h UI+CLI `driver=warehouse`, `n_times=3600`, matrix **72000**,
  epoch 19:36:25Z. gpu-0..5 nonzero 2311/3600 (honest recycle gaps).

## Next

Analog **496555** after 20:00Z close, then DROP RANGE 496555. Retry
`ALTER VIEW … NOT IN` when HMS accepts `alter_table`. Do not analog
the open hour.
