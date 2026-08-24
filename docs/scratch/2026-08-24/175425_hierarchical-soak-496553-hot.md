# Hierarchical soak tick (17:54Z)

Hour **496553** still hot (~54 min). Below analog threshold (≥55 min /
18:00Z close). Impala FE already `IMPALA_BUILD_OK`. Do not analog.

## Sampler / engine

Jsonl sidecar `pid 36619` (~4.0 h, sample-only) still up. Engine recycled
again at **17:50:24** (`pid 2241474`); previous `pid 2018647` is gone.
Warehouse ingest recovered: `ticks=60 inserted=360` by 17:54:12 (first
30 ticks took ~2.8 min during vLLM preload). Lag ~0.8 s. Live sample
`power_w=6.7–18.4` `mem=24027` on gpu-0 (thinking loading), other GPUs
idle `mem=3` (real DCGM after `gpu_cleanup`). Jsonl 3254 ticks / 19524
rows vs Kudu **16668** rows (2778 s) — short **476** warehouse ticks
from 17:27 and 17:50 recycles, not padded.

## Proven (no fake rows)

- `SHOW RANGE` starts at `VALUE = 496553` … `496569`. UNION honest:

  | hour   | store   | count |
  |--------|---------|-------|
  | 496550 | Iceberg | 20334 |
  | 496551 | Iceberg | 20460 |
  | 496552 | Iceberg | 20430 |
  | 496553 | Kudu    | 16668 live |

- Strip=1h UI `driver=warehouse`, `n_times=3600`, matrix **72000**,
  epoch 17:54:14Z. gpu-0..5 nonzero 3116/3600 (honest recycle gaps).

## Next

Analog **496553** after 18:00Z close, then DROP RANGE 496553. Retry
`ALTER VIEW … NOT IN` when HMS accepts `alter_table`.
