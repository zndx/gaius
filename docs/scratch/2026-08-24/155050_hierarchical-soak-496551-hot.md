# Hierarchical soak tick (15:50Z)

Hour **496551** still hot (~50 min, 3027 s). Below analog threshold
(≥55 min / 16:00Z close). Impala FE already `IMPALA_BUILD_OK`.
Do not analog.

## Sampler / engine

Jsonl sidecar `pid 36619` (~1.9 h, sample-only) and engine `pid 947557`
(~18 min this life, ingest since 15:32:25) still up. Lag ~0. Live
sample `power_w=88/121` `util=27/100` `mem=21331` (real DCGM). Jsonl
3025 ticks vs Kudu **17214** rows (2869 s) — short the 15:32 restart
hole plus DCGM vs jsonl 1 s mismatches. No fake backfill.

## Proven (no fake rows)

- `SHOW RANGE` `VALUE = 496551` … `496569`. UNION honest:

  | hour   | store   | count |
  |--------|---------|-------|
  | 496549 | Iceberg | 19752 |
  | 496550 | Iceberg | 20334 |
  | 496551 | Kudu    | 17214 live |

- Strip=1h UI `driver=warehouse`, `n_times=3600`, matrix **72000**.
  gpu-0..5 nonzero 3413/3600.

## Next

Analog **496551** after 16:00Z close, then DROP RANGE 496551. Retry
`ALTER VIEW … NOT IN` when HMS accepts `alter_table`.
