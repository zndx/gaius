# Hierarchical soak tick (17:21Z)

Hour **496553** still hot (~21 min). Impala FE already `IMPALA_BUILD_OK`.
Do not analog — not closed (18:00Z). Hour **496552** already Iceberg.

## Sampler / engine

Jsonl sidecar `pid 36619` (~3.5 h, sample-only) and engine `pid 947557`
(~109 min this life) still up. Lag ~0.5 s. Live sample `power_w=111/129`
`util=25/100` `mem=21333` (real DCGM). No fake rows.

## Proven (no fake rows)

- `SHOW RANGE` starts at `VALUE = 496553`. UNION honest:

  | hour   | store   | count |
  |--------|---------|-------|
  | 496550 | Iceberg | 20334 |
  | 496551 | Iceberg | 20460 |
  | 496552 | Iceberg | 20430 |
  | 496553 | Kudu    | 7356 live |

- Strip=1h UI `driver=warehouse`, `n_times=3600`, matrix **72000**.
  gpu-0..5 nonzero 3377/3600.

## Next

Analog **496553** after 18:00Z close, then DROP RANGE 496553. Retry
`ALTER VIEW … NOT IN` when HMS accepts `alter_table`.
