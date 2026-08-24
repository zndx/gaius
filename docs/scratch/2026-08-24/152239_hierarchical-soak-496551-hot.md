# Hierarchical soak tick (15:22Z)

Hour **496551** still hot (~22 min). Impala FE already `IMPALA_BUILD_OK`.
Do not analog — not closed (16:00Z). Hour **496550** already Iceberg.

## Sampler

Jsonl sidecar `pid 36619` (~1.5 h this life, sample-only, `kudu_via=engine_fdw`,
`inserted:0`) and engine warehouse ingest `pid 267627` (~64 min) still up.
Live lag ~0.2 s. No fake rows.

## Proven (no fake rows)

- Kudu `SHOW RANGE` is `VALUE = 496551` … `496569`. **496550 is gone**
  (DROP RANGE applied since 15:11 analog). This tick **ADD RANGE 566–569**
  (Impala catalog reload fault; SHOW RANGE verified). UNION no longer
  double-counts:

  | hour   | store   | count |
  |--------|---------|-------|
  | 496537 | Iceberg | 12156 |
  | …      | Iceberg | …     |
  | 496549 | Iceberg | 19752 |
  | 496550 | Iceberg | 20334 |
  | 496551 | Kudu    | live  |

- Iceberg 496550 sample `power_w=125` `util=100` `mem=21332` (real DCGM).
  Live Kudu sample `power_w≈98–127` `mem=21225` on GPUs 0–3.
- Live `gpu_metrics` VIEW is still `tier0 UNION ALL tier1` **without**
  `NOT IN`. `ALTER VIEW` this tick hit HMS `TTransportException`
  (`#SL.00000029.RANGEDDL`). Honest today because analoged hours are
  not in Kudu; analog-before-DROP next hour will double-count until
  DROP or the NOT IN lands.
- Strip=1h UI+gRPC `driver=warehouse`, `n_times=3600`, matrix **72000**.
  gpu-0..5 nonzero 3434/3600. `gaius-cli` import still broken
  (`NEXT_QUESTION_RESERVE_TOKENS` missing from dirty `cognition_buffer.py`).

## Next

Analog **496551** after 16:00Z close, then DROP RANGE 496551. Retry
`ALTER VIEW … NOT IN` from `config/platform/gpu-metrics-iceberg.sql`
when HMS accepts `alter_table`. Do not analog the open hour.
