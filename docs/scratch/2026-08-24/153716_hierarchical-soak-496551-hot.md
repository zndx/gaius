# Hierarchical soak tick (15:37Z)

Hour **496551** still hot (~37 min). Impala FE already `IMPALA_BUILD_OK`.
Do not analog — not closed (16:00Z). Hour **496550** already Iceberg.

## Sampler / engine

Jsonl sidecar `pid 36619` (~1.7 h, sample-only, `kudu_via=engine_fdw`)
still up. Engine **restarted 15:32:17Z** (`pid 947557`, was 267627).
Warehouse ingest resumed `ticks=1` at 15:32:25; lag ~0.2 s. Honest
Kudu hole **15:32:14–15:32:25** (~11 s). Scattered 1 s jsonl/DCGM
mismatches not backfilled (would double-sample, not a closed gap).

Live sample `power_w≈7–21` `mem=21117` on GPUs 0–3 (thinking idle).

## Proven (no fake rows)

- `SHOW RANGE` `VALUE = 496551` … `496569`. UNION honest:

  | hour   | store   | count |
  |--------|---------|-------|
  | 496549 | Iceberg | 19752 |
  | 496550 | Iceberg | 20334 |
  | 496551 | Kudu    | live (~12546 / 2091 s) |

- Strip=1h UI+gRPC `driver=warehouse`, `n_times=3600`, matrix **72000**.
  gpu-0..5 nonzero 3451/3600. `gaius-cli` import still broken
  (`NEXT_QUESTION_RESERVE_TOKENS`).

## Next

Analog **496551** after 16:00Z close, then DROP RANGE 496551. Retry
`ALTER VIEW … NOT IN` when HMS accepts `alter_table`. Do not analog
the open hour.
