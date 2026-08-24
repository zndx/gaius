# Hierarchical soak tick (16:51Z)

Hour **496552** still hot (~51 min, 3055 s). Below analog threshold
(≥55 min / 17:00Z close). Impala FE already `IMPALA_BUILD_OK`.
Do not analog.

## Sampler / engine

Jsonl sidecar `pid 36619` (~3.0 h, sample-only) and engine `pid 947557`
(~79 min this life) still up. Lag ~0.7 s. Live sample `power_w=53/61`
`util=0` `mem=21333` (real DCGM). Jsonl 3055 ticks vs Kudu **17304**
rows (2884 s) — DCGM vs jsonl mismatch, not padded.

## Proven (no fake rows)

- `SHOW RANGE` starts at `VALUE = 496552`. UNION honest:

  | hour   | store   | count |
  |--------|---------|-------|
  | 496549 | Iceberg | 19752 |
  | 496550 | Iceberg | 20334 |
  | 496551 | Iceberg | 20460 |
  | 496552 | Kudu    | 17304 live |

- Strip=1h UI `driver=warehouse`, `n_times=3600`, matrix **72000**.
  gpu-0..5 nonzero 3397/3600.

## Next

Analog **496552** after 17:00Z close, then DROP RANGE 496552. Retry
`ALTER VIEW … NOT IN` when HMS accepts `alter_table`.
