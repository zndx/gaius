# Hierarchical storage soak — Kudu first, then Iceberg+HDF5

Started 2026-08-24 ~01:09Z (jsonl) / 01:35Z (1 Hz daemon). Real tinybox
nvidia-smi (6× RTX 4090) written to `/tmp/gpu-metrics-hour.jsonl`.

## Status 2026-08-24 02:45Z

- Sampler still C++ (`kudu_via=cpp`), jsonl ~86 min (hours 496537+496538).
- `catalog_tables` now has `signals_dataproducts.gpu_metrics_tier0` (KUDU, FQDN masters).
- `kudu.properties` FQDN; Polarisfork `warehouse=signals` + OAuth `admin:admin`;
  `config/impala/kudu-jaas.conf` for catalogd JVM keytab.
- IcebergMetaProvider previously died with `Please specify a warehouse`
  (`iceberg.rest.warehouse` is not the Iceberg/Trino key). Polarisfork catalog
  `signals` exists; analog `.h5` is on RustFS. HS2 UNION still not live
  (Java Kudu TGT + Iceberg REST warehouse mapping).
- Gaius Strip=1h still `driver=warehouse` via FDW `kudu_scan`.

## Status 2026-08-24 02:32Z

Live proof (no fake rows):

- jsonl 1 Hz sampler still running (`scripts/gpu_metrics_kudu_ingest.py`,
  C++ upsert every 30 ticks via `/tmp/gpu_kudu_ingest`).
- Kudu `impala::signals_dataproducts.gpu_metrics_tier0` has the real ticks
  (C++ create + backfill; HS2 CREATE still KUDU-2121).
- devenv Postgres `:5455` foreign table `gpu_metrics` → `kudu_scan`.
- Gaius Discover Strip=`1h warehouse`: Engine `CognitionWaterfall`
  `driver=warehouse`, `n_times=3600`, `n_channels=20`, matrix 72000.
  CLI `/thoughts waterfall 3600` and UI
  `http://127.0.0.1:9890/api/gaius/v1/cognition/waterfall?window_s=3600`.
- Closed hour 496537 analog:
  `s3://signals-dataproducts/iceberg/gpu_metrics_tier1/epoch_hour=496537/gpu_metrics_hour_496537.h5`
  (12156 rows) plus hdf5-iceberg pointer table under
  `s3://signals-dataproducts/iceberg/gpu_metrics_tier1_meta/`.

Still open (fail-fast, not stubbed):

- Impala Java Kudu client TGT (`missing or expired TGT` after FQDN
  `JAVA_TOOL_OPTIONS`). HMS-free catalog does not persist Iceberg
  `gpu_metrics_tier1`; HS2 UNION view not live yet.
- `#SL.00000022.HDF5REG` was duplicate FormatModel registration; FE now
  logs and continues. Iceberg CREATE said success once, then catalog load
  treated the name as Kudu.

## Query path under test

Gaius Discover strip (`window_s=3600`) → Engine gRPC → devenv Postgres
`:5455` `impala_fdw` foreign table `gpu_metrics` → Impala HS2 →
`gpu_metrics_tier0` (Kudu, hot hour) ∪ `gpu_metrics_tier1` (Iceberg HDF5).

Live 60 s strip is unchanged (10 Hz ring). Longer windows fail-fast with
`#COG.00000031.NOWHFDW` until the FDW table answers.

## What is running now

- GPU ingest daemon (1 Hz, jsonl always). Status:
  `/tmp/gpu-metrics-ingest.status`
- Impala isolated rebuild (`FileFormat.HDF5` scanner + SASL includes).
  Log: `/tmp/impala-build-hdf5.log`
- Iceberg `1.11.0-signals-hdf5` republished including `iceberg-orc`
  (Impala FE previously 403'd CDP for a missing local POM).

## Blockers being debugged (expected)

1. **Impala Java → Kudu SASL.** `CREATE TABLE … STORED AS KUDU` fails
   with “Couldn't find a valid master … no token is available”. Catalogd
   C++ has a keytab; the Kudu *Java* client used for the HMS-integration
   probe does not pick up a TGT on Java 21 (`KUDU-2121`: `Sasl.createSaslClient`
   not inside `Subject.callAs`, Netty thread). Atlas Kudu tables fail to
   load for the same reason. Fix in flight:
   - `devenv.nix` `hmsFreeJavaOpts`: FQDN masters +
     `javax.security.auth.useSubjectCredsOnly=false`
   - C++ `kudu` CLI create + `impala_fdw` `kudu_scan` bypasses Impala Java
   - Restart catalogd/impalad after JAVA_TOOL_OPTIONS change
2. **FDW.** `impala_kudu_srv` exists; `CREATE USER MAPPING FOR signals`
   is missing (`user mapping not found`). Apply
   `config/platform/gpu-metrics-fdw.sql` after Kerberos mapping.
3. **HDF5 scanner.** `HdfsHdf5Scanner` now uses `stream_->filename()`,
   implements `InitNewRange` + `file_format()=HDF5`, maps INT/BIGINT/FLOAT.
   BE `ExecHdf5` linked; FE blocked on iceberg-orc until this republish.

## DDL / analog

- Kudu: `config/platform/gpu-metrics-kudu.sql` + live `ADD RANGE` in
  `scripts/gpu_metrics_kudu_ingest.py` (hour tablets).
- Iceberg: `config/platform/gpu-metrics-iceberg.sql` (`write.format.default=hdf5`).
- Analog writer: `write_warehouse_analog` (power/util/mem/temp stacked
  series, Timestamps). Fingerprint analog (7/5/56) unchanged.
- Settle: `scripts/gpu_metrics_tier_up.py --hour <epoch_hour>`.

## After the closed hour

1. Verify Kudu row count ≥ jsonl ticks × 6.
2. `gpu_metrics_tier_up.py` → analog `.h5` → `s3://signals-dataproducts/iceberg/gpu_metrics_tier1/`.
3. Impala `CREATE TABLE gpu_metrics_tier1` + `gpu_metrics` UNION view.
4. FDW `SELECT` a 1h window that spans Kudu (current hour) and Iceberg
   (settled hour).
5. Discover landing: Strip = `1h warehouse`. Fail-fast if empty.
