# Hierarchical soak tick (17:41Z)

Hour **496553** still hot (~41 min). Impala FE already `IMPALA_BUILD_OK`.
Do not analog — not closed (18:00Z). Hour **496552** already Iceberg.

## Sampler / engine

Jsonl sidecar `pid 36619` (~3.8 h, sample-only, `kudu_via=engine_fdw`,
`inserted:0`) still up. Engine recycled at **17:27:18** (`pid 2018647`,
this life ~14 min) after `recycle-on-land`; previous `pid 947557` is gone.
Warehouse ingest recovered: `ticks=690 inserted=4140` by 17:40:59.
Lag ~0.3 s. Live sample `power_w=119/137` `util=100` `mem=21331` (real
DCGM). Jsonl 2466 ticks / 14796 rows vs Kudu **13428** rows (2238 s) —
short **228** warehouse ticks from the 17:21–17:32 recycle, not padded.

## Proven (no fake rows)

- `SHOW RANGE` starts at `VALUE = 496553` … `496569`. UNION honest:

  | hour   | store   | count |
  |--------|---------|-------|
  | 496548 | Iceberg | 21600 |
  | 496549 | Iceberg | 19752 |
  | 496550 | Iceberg | 20334 |
  | 496551 | Iceberg | 20460 |
  | 496552 | Iceberg | 20430 |
  | 496553 | Kudu    | 13428 live |

- Iceberg 496552 sample `power_w=111–125` `util=100` `mem=21333` (real
  DCGM). Strip=1h UI `driver=warehouse`, `n_times=3600`, matrix **72000**.
  gpu-0..5 nonzero 3304/3600 (honest recycle gap).
- `ALTER VIEW … NOT IN` still HMS `TTransportException` (`alter_table`,
  socket closed by peer). Honest after DROP; analog-before-DROP next
  hour will double-count until DROP or the view lands.

## Next

Analog **496553** after 18:00Z close, then DROP RANGE 496553. Retry
`ALTER VIEW … NOT IN` when HMS accepts `alter_table`. Do not analog
the open hour.
