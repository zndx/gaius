# Hierarchical soak tick (19:56Z)

Hour **496555** still hot (~56 min elapsed, ~4 min to close). Analog
waits for **20:00Z** so the last ticks land in Kudu. Impala FE already
`IMPALA_BUILD_OK`. Do not analog the open hour. Hour **496554** already
Iceberg (13974).

## Sampler / engine

Jsonl sidecar `pid 36619` (~6.0 h, sample-only) still up. Engine
`pid 3275835` (started 19:44:27) **wedged**: warehouse ingest last
`ticks=210` at 19:48:13, FDW `max(ts_ns)` frozen 11142 rows, lag grew
to **~189 s**. DCGM `:9400` still live. Same asyncio loop was busy with
sync HuggingFace/ColBERT loads and optillm `:8000` 500s (`:8082` 404).
`devenv processes restart` did not replace the PID (Rsl). SIGTERM then
SIGKILL; new engine `pid 3366615` (ingest `ticks=1` at 19:55:35).
Lag ~0.7 s after restart. Live sample `power_w=5.7–20.4` `mem=3` (real
DCGM after `gpu_cleanup`). Jsonl 3380 ticks / 20280 rows vs Kudu
**11208** rows (1868 s) — short **~1512** warehouse ticks from earlier
recycles plus this stall, not padded.

## Proven (no fake rows)

- `SHOW RANGE` starts at `VALUE = 496555` … `496574`. UNION honest:

  | hour   | store   | count |
  |--------|---------|-------|
  | 496552 | Iceberg | 20430 |
  | 496553 | Iceberg | 16770 |
  | 496554 | Iceberg | 13974 |
  | 496555 | Kudu    | 11208 live |

- Strip=1h UI+CLI `driver=warehouse` after restart, `n_times=3600`,
  matrix **72000**, epoch 19:56:04Z. gpu-0..5 nonzero 2107/3600
  (honest recycle/stall gaps). Pre-restart UI curl timed out (28) on
  the wedged engine.

## Next

Analog **496555** after 20:00Z close, then DROP RANGE 496555. Retry
`ALTER VIEW … NOT IN` when HMS accepts `alter_table`. Warehouse ingest
must not share a blocked engine event loop with sync HF loads.
