# Hierarchical soak: Java Kudu SASL unblocked (04:46Z)

Sampler still C++ (`pid 2989721`, jsonl `/tmp/gpu-metrics-hour.jsonl`).
Impala FE rebuild already `IMPALA_BUILD_OK`.

## Proven this slice (no fake rows)

- Java Kudu client now authenticates: lab `/etc/hosts` maps
  `tinybox.dev.vista.zndx.org` → `127.0.0.1`. Patched `ConnectToCluster`
  + `ServerInfo` keep the FQDN for GSSAPI (`kudu/tinybox…` not
  `kudu/127.0.0.1`). HS2 `SELECT` on `gpu_metrics_tier0` returns **80240**
  real nvidia-smi rows (hours 496537–496540).
- Iceberg HDF5 `gpu_metrics_tier1` still 12156+21930+21594.
- HS2 `UNION ALL` subquery of tier0∪tier1 runs (double-count until Kudu
  DROP RANGE). Persisted `CREATE VIEW` still HMS
  `getCurrentNotificationEventId`.
- FDW `:5455` `gpu_metrics` `kudu_scan` lag ~0.4 s. Strip=1h CLI+UI
  `driver=warehouse`, `n_times=3600`, matrix 72000.
- C++ jsonl upsert **70734** this pass. Sampler kept alive.

## Still fail-fast

- HMS-free `CREATE VIEW gpu_metrics` not stored — catalog_tables is
  KUDU|ICEBERG only. Do **not** DROP Kudu closed hours until FDW can
  read the UNION (HS2 GSSAPI on `impala_sql`, or a catalog view).
- Sidecar ingest `ModuleNotFoundError: impala` on HS2; C++ path is enough.
