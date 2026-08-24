# Engine is the Kudu writer (Postgres impala_fdw)

The C++ sidecar is not an honest soak of the product. Gaius engine now
`INSERT`s `gpu_metrics_tier0` at 1 Hz through devenv Postgres `:5455`
(`kudu_scan` UPSERT). Sidecar ingest refuses to start.

## Verified 13:50Z

- `warehouse ingest started` then `ticks=30 inserted=180` (6 GPUs)
- `gpu_metrics_tier0` COUNT rose ~30 rows / 5 s; lag ~0.5 s
- No sidecar process
- `impala_fdw_exec` `DROP RANGE PARTITION VALUE = 496566` verified via
  `SHOW RANGE PARTITIONS` (whole single-value hour range; HASH buckets
  included). Impala still throws `TableLoadingException` after Kudu ALTER
  succeeds; the FDW reconnects and checks SHOW RANGE.

## Schema

No wipe. Live table is `PARTITION BY HASH (gpu_index), RANGE (epoch_hour)`
with `VALUE = <hour>`. Expire SQL is Impala
`ALTER TABLE … DROP RANGE PARTITION VALUE = <hour>`, not a partial slice
and not row DELETE.

Warehouse ingest starts after the engine DB pool, before vLLM preload.
