# Hierarchical storage soak — Kudu first, then Iceberg+HDF5

Started 2026-08-24 ~01:09Z (jsonl) / 01:35Z (1 Hz daemon). Real tinybox
nvidia-smi (6× RTX 4090) written to `/tmp/gpu-metrics-hour.jsonl`.

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
