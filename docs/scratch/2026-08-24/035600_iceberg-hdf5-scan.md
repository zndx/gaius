# Iceberg HDF5 file scan (03:56Z)

HS2 now materializes analog HDF5 hours 496537/496538 as real rows:

```
SELECT * FROM signals_dataproducts.gpu_metrics_tier1 LIMIT 2
496538  1787536800539543040  0  8.0  0.0  21332.0  49.0
```

`GROUP BY epoch_hour` = 12156 + 21930. Local FormatModel and Impala JNI scanner agree.

Fixes this slice: Polarisfork `s3://` → `FsType.S3` (was TreeMap null NPE);
HMS-free `GetNullPartitionName`; BE `FbIcebergDataFileFormat_HDF5`;
`ReachedLimitShared`; slots by `col_pos()`.

FDW `:5455` `gpu_metrics` stays `kudu_scan` (HS2 GSSAPI not in `impala_sql`).
CLI `/thoughts waterfall 3600` → `driver=warehouse`. Sampler still C++.
Do not DROP Kudu ranges yet — 1h strip still reads tablets.
