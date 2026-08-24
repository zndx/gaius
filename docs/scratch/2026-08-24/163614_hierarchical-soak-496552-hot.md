# Hierarchical soak tick (16:36Z)

Hour **496552** still hot (~36 min). Impala FE already `IMPALA_BUILD_OK`.
Do not analog — not closed (17:00Z). Hour **496551** already Iceberg.

## Sampler / engine

Jsonl sidecar `pid 36619` (~2.7 h, sample-only) and engine `pid 947557`
(~64 min this life) still up. Lag ~0.6 s. Live sample `power_w=110/126`
`util=100` `mem=21333` (real DCGM). Jsonl 2153 ticks vs Kudu **12378**
rows (2063 s) — small DCGM vs jsonl mismatch, not padded.

## Proven (no fake rows)

- `SHOW RANGE` starts at `VALUE = 496552`. UNION honest:

  | hour   | store   | count |
  |--------|---------|-------|
  | 496549 | Iceberg | 19752 |
  | 496550 | Iceberg | 20334 |
  | 496551 | Iceberg | 20460 |
  | 496552 | Kudu    | 12378 live |

- Strip=1h UI `driver=warehouse`, `n_times=3600`, matrix **72000**.
  gpu-0..5 nonzero 3405/3600.

## Next

Analog **496552** after 17:00Z close, then DROP RANGE 496552. Retry
`ALTER VIEW … NOT IN` when HMS accepts `alter_table`.
