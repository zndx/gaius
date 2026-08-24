# Hierarchical soak tick (18:36Z)

Hour **496554** still hot (~36 min). Below analog threshold (≥55 min /
19:00Z close). Impala FE already `IMPALA_BUILD_OK`. Do not analog.
Hour **496553** already Iceberg (16770).

## Sampler / engine

Jsonl sidecar `pid 36619` (~4.7 h, sample-only, `kudu_via=engine_fdw`,
`inserted:0`) still up. Engine recycled at **18:33:44** (`pid 2647023`);
previous `pid 2427158` (18:11:56Z) is gone. Warehouse ingest recovered:
`ticks=90 inserted=540` by 18:35:51 (first tick 18:34:12 after vLLM
preload). Lag ~0.9 s. Live sample `power_w=6.3–17.9` `mem=3` all GPUs
(real DCGM after `gpu_cleanup`; thinking not yet reloaded). Jsonl 2205
ticks / 13230 rows vs Kudu **7182** rows (1197 s) — short **~1000**
warehouse ticks from 18:00–18:11 (prior life start) and the 18:33
recycle, not padded.

## Proven (no fake rows)

- `SHOW RANGE` starts at `VALUE = 496554` … `496573`. UNION honest:

  | hour   | store   | count |
  |--------|---------|-------|
  | 496550 | Iceberg | 20334 |
  | 496551 | Iceberg | 20460 |
  | 496552 | Iceberg | 20430 |
  | 496553 | Iceberg | 16770 |
  | 496554 | Kudu    | 7182 live |

- Strip=1h UI+CLI `driver=warehouse`, `n_times=3600`, matrix **72000**,
  epoch 18:36:31Z. gpu-0..5 nonzero 2041/3600 (honest recycle gaps).

## Next

Analog **496554** after 19:00Z close, then DROP RANGE 496554. Retry
`ALTER VIEW … NOT IN` when HMS accepts `alter_table`. Do not analog
the open hour.
