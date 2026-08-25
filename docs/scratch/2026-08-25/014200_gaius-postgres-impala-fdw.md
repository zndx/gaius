# Gaius Postgres as FDW client of system Impala/Kudu

Kudu, Impala HS2, and RustFS stay where they are (Signals / the lattice).
Gaius `zndx_gaius :5444` now has `impala_fdw` + `gpu_metrics_tier0/1`
pointing at that HS2 (`tinybox.dev.vista.zndx.org:21050`). Signals `:5455`
is not unwired.

`just warehouse-fdw` copies the already-built Signals `.so` (same PG 16)
and registers the server. Engine `warehouse_dsn()` defaults to local
Gaius Postgres. `GAIUS_WAREHOUSE_USE_SIGNALS=1` still uses `:5455`.

The Gaius postmaster needs `KRB5_CONFIG` from the Signals devenv KDC
(same realm the warehouse postgres already uses). Without it, kudu_scan
kinit cannot find `DEV.VISTA.ZNDX.ORG`.
