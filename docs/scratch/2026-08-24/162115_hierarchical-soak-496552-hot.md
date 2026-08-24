# Hierarchical soak tick (16:21Z)

Hour **496552** still hot (~21 min). Impala FE already `IMPALA_BUILD_OK`.
Do not analog — not closed (17:00Z). Hour **496551** already Iceberg.

## Sampler / engine

Jsonl sidecar `pid 36619` (~2.5 h, sample-only) and engine `pid 947557`
(~49 min this life) still up. Lag ~0.8 s. Live sample `power_w=106/127`
`util=24/100` `mem=21331` (real DCGM). No fake rows.

## Proven (no fake rows)

- `SHOW RANGE` starts at `VALUE = 496552`. UNION honest:

  | hour   | store   | count |
  |--------|---------|-------|
  | 496549 | Iceberg | 19752 |
  | 496550 | Iceberg | 20334 |
  | 496551 | Iceberg | 20460 |
  | 496552 | Kudu    | 7440 live |

- Strip=1h UI `driver=warehouse`, `n_times=3600`, matrix **72000**.
  gpu-0..5 nonzero 3432/3600.

## Next

Analog **496552** after 17:00Z close, then DROP RANGE 496552. Retry
`ALTER VIEW … NOT IN` when HMS accepts `alter_table`.
