# Hierarchical soak continue (03:24Z)

Live tinybox nvidia-smi jsonl `/tmp/gpu-metrics-hour.jsonl` (1 Hz). Sampler
`scripts/gpu_metrics_kudu_ingest.py` still C++ (`kudu_via=cpp`).

## Proven this slice (no fake rows)

- jsonl hours 496537 (12156 rows), 496538 (21930, closed), 496539 (hot).
- C++ upsert backfill so Kudu matches jsonl; FDW `:5455` `gpu_metrics`
  `kudu_scan` counts those hours.
- Closed-hour analog: `gpu_metrics_tier_up.py --hour 496538` →
  `s3://signals-dataproducts/iceberg/gpu_metrics_tier1/epoch_hour=496538/`
  and Iceberg table data prefix
  `s3://…/signals_dataproducts/gpu_metrics_tier1/data/epoch_hour=496538/`.
- hdf5-iceberg register: 4 analog files, pointer
  `s3://…/gpu_metrics_tier1_meta/telemetry/hdf5_datasets/parts.parquet`.
- Polarisfork `signals_dataproducts.gpu_metrics_tier1` snapshots
  12156+21930 = 34086 records, `write.format.default=hdf5`.
- Impala isolated FE rebuild already `IMPALA_BUILD_OK`; catalogd/impalad
  were down on duplicate REST warehouse keys. `polaris.properties` now
  has Iceberg `warehouse=signals` only. HS2 `:21050` is up.
- `SHOW TABLES IN signals_dataproducts` → `gpu_metrics_tier0` +
  `gpu_metrics_tier1`. `DESCRIBE FORMATTED` Iceberg location + hdf5.
- HS2 `SELECT count(*) FROM gpu_metrics_tier1` = **34086** (Iceberg
  snapshot stats). Local `IcebergHdf5Scanner` on analog `.h5` returns
  21930 real rows.
- Gaius CLI `/thoughts waterfall 3600` → `driver=warehouse`,
  `n_times=3600`, `n_channels=20`.

## Still fail-fast (not stubbed)

- Impala Java Kudu client TGT (`KUDU-2121` + advertised `127.0.0.1`).
  HS2 `CREATE VIEW gpu_metrics AS tier0 UNION ALL tier1` cannot load
  `gpu_metrics_tier0`. FDW `gpu_metrics` stays `kudu_scan` of hot Kudu
  (all hours still in tablets; no DROP RANGE yet).
- HS2 `SELECT * FROM gpu_metrics_tier1 LIMIT 3` NPEs
  (`Comparable.compareTo` k1=null) in the Iceberg file-scan planner.
  Local JNI analog reader is fine. Do not drop the Kudu hour until a
  file scan returns the analog rows.

## DDL / analog

- Registerer: `scripts/IcebergHdf5Register.java` (Polarisfork REST,
  `FileFormat.HDF5`, partition `epoch_hour`).
- FE: `IcebergScanNode.populateFileFormats` accepts `FbIcebergDataFileFormat.HDF5`.
