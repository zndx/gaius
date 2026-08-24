# Hierarchical soak tick (19:21Z)

Hour **496555** still hot (~21 min). Below analog threshold (≥55 min /
20:00Z close). Impala FE already `IMPALA_BUILD_OK`. Do not analog.
Hour **496554** already Iceberg (13974).

## Sampler / engine

Jsonl sidecar `pid 36619` (~5.5 h, sample-only) still up. Engine recycled
at **19:16:55** (`pid 3032675`); previous `pid 2967194` (19:10Z restart)
is gone. Warehouse ingest recovered: `ticks=180 inserted=1080` by
19:20:43 (first tick 19:17:19). Lag ~0.9 s. Live sample `power_w=6.1–19.1`
`mem=21117` on GPUs 0–3 (thinking loaded), gpu-4/5 idle `mem=3` (real
DCGM). Jsonl 1268 ticks / 7608 rows vs Kudu **2946** rows (491 s) — short
**~777** warehouse ticks from 19:00–19:10 engine-down and the 19:16
recycle, not padded.

## Proven (no fake rows)

- `SHOW RANGE` starts at `VALUE = 496555` … `496574`. UNION honest:

  | hour   | store   | count |
  |--------|---------|-------|
  | 496552 | Iceberg | 20430 |
  | 496553 | Iceberg | 16770 |
  | 496554 | Iceberg | 13974 |
  | 496555 | Kudu    | 2946 live |

- Strip=1h UI+CLI `driver=warehouse`, `n_times=3600`, matrix **72000**,
  epoch 19:21:24Z. gpu-0..5 nonzero 2286/3600 (honest recycle gaps).

## Next

Analog **496555** after 20:00Z close, then DROP RANGE 496555. Retry
`ALTER VIEW … NOT IN` when HMS accepts `alter_table`. Do not analog
the open hour.
