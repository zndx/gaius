# Hierarchical soak tick (18:51Z)

Hour **496554** still hot (~51 min). Below analog threshold (≥55 min /
19:00Z close). Impala FE already `IMPALA_BUILD_OK`. Do not analog.
Hour **496553** already Iceberg (16770).

## Sampler / engine

Jsonl sidecar `pid 36619` (~5.0 h, sample-only) still up. Engine recycled
again at **18:49:56** (`pid 2807451`); previous `pid 2647023` (18:33:44Z)
is gone. Warehouse ingest recovered: `ticks=30 inserted=180` by 18:50:37
(first tick 18:50:05). Lag ~0.1 s. Live sample `power_w=5.0–18.2`
`mem=3` all GPUs (real DCGM after `gpu_cleanup`; thinking not loaded).
Jsonl 3060 ticks / 18360 rows vs Kudu **11208** rows (1868 s) — short
**~1192** warehouse ticks from 18:00–18:11 start plus 18:33 and 18:49
recycles, not padded.

## Proven (no fake rows)

- `SHOW RANGE` starts at `VALUE = 496554` … `496573`. UNION honest:

  | hour   | store   | count |
  |--------|---------|-------|
  | 496550 | Iceberg | 20334 |
  | 496551 | Iceberg | 20460 |
  | 496552 | Iceberg | 20430 |
  | 496553 | Iceberg | 16770 |
  | 496554 | Kudu    | 11208 live |

- Strip=1h UI+CLI `driver=warehouse`, `n_times=3600`, matrix **72000**,
  epoch 18:51:18Z. gpu-0..5 nonzero 1953/3600 (honest recycle gaps;
  newest ~11 s still filling after 18:49 recycle).

## Next

Analog **496554** after 19:00Z close, then DROP RANGE 496554. Retry
`ALTER VIEW … NOT IN` when HMS accepts `alter_table`. Do not analog
the open hour.
