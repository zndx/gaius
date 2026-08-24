# Hierarchical soak: closed hour 496540 on Iceberg (05:13Z)

Sampler alive (`kudu_ok` after ADD RANGE). Hour rolled to 496541.

## Proven (no fake rows)

- jsonl hour 496540 = **19968** analog HDF5 rows on RustFS + Polarisfork.
  HS2 Iceberg scan returns those rows.
- Hot hour 496541 is back in Kudu (FDW lag ~0).
- Strip=1h CLI+UI `driver=warehouse`, `n_times=3600`, matrix 72000.

## Fail-fast leftovers

- Sidecar C++ create used to skip ADD RANGE if the table existed — source
  fixed; `/tmp/gpu_kudu_create` binary not rebuilt this slice (150 MiB).
- Do **not** DROP Kudu 496540 until FDW can read the Impala UNION view
  (`impala_sql` HS2 GSSAPI still missing).
