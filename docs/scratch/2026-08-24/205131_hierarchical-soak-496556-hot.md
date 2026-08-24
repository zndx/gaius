# Hierarchical soak tick (20:51Z)

Hour **496556** still hot (~51 min). Below analog threshold (≥55 min /
21:00Z close). Impala FE already `IMPALA_BUILD_OK`. Do not analog.
Hour **496555** already Iceberg (12486).

## Sampler / engine

Jsonl sidecar `pid 36619` (~7.0 h, sample-only) still up. Engine recycled
at **20:45:25** (`pid 3810930`); previous `pid 3711380` (20:35Z restart)
is gone. Warehouse ingest recovered: `ticks=270 inserted=1620` by
20:50:57 (first this life ~20:45:37). Lag ~0.9 s. Live sample
`power_w=122–137` `util=100` `mem=21327` on GPUs 0–3, gpu-5 `mem=3`
(real DCGM). Jsonl 3053 ticks / 18318 rows vs Kudu **13152** rows
(2192 s) — short **~861** warehouse ticks from 20:35 and 20:45
recycles plus earlier gaps, not padded.

## Proven (no fake rows)

- `SHOW RANGE` starts at `VALUE = 496556` … `496578`. UNION honest:

  | hour   | store   | count |
  |--------|---------|-------|
  | 496553 | Iceberg | 16770 |
  | 496554 | Iceberg | 13974 |
  | 496555 | Iceberg | 12486 |
  | 496556 | Kudu    | 13152 live |

- Strip=1h UI+CLI `driver=warehouse`, `n_times=3600`, matrix **72000**,
  epoch 20:51:15Z. gpu-0..5 nonzero 2401/3600 (honest recycle gaps).

## Next

Analog **496556** after 21:00Z close, then DROP RANGE 496556. Retry
`ALTER VIEW … NOT IN` when HMS accepts `alter_table`. Do not analog
the open hour. Keep sampler 36619 and engine ingest.
