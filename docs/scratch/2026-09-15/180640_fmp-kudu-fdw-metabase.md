# FMP Kudu tier0 + warehouse.v_fmp_* + fail-closed Metabase hook

The Polarisfork Iceberg `gaius.fmp.*` land was the first slice. Metabase
does not query Polarisfork; it queries Postgres. This hop is the THS path
the design asked for.

## Land path

```
PrepareFmpWarehouse → STP FmpWarehouseFlow (gpu_tokens=0)
  FmpCall catalog (Starter Annual)
  flatten → INSERT fmp_*_tier0 via Gaius :5444 impala_fdw kudu_scan
  ADD RANGE PARTITION [today, today+2d) (catch-all VALUES < 0 at create)
  notify MetabaseEngine.ProjectWarehouse (FederationSurfaces, fail-closed)
```

Polarisfork `gaius.fmp.*` remains a best-effort copy. Iceberg settle
(`fmp_*_tier1`) is still PENDING, same as nautilus.

## Apply (no Python impyla)

THS runtime is Postgres `impala_fdw` `kudu_scan` (libkudu_client in the
FDW). Table create is `signals_kudu_create` (same client). Catalog rows
are SQL on `:5455` `signals_catalog`. Impyla is not on this path.

1. Signals: `devenv shell -- scripts/build-kudu-tools.sh signals_kudu_create`
   then `signals_kudu_create fmp_profile_tier0` (and filings/earnings).
2. `psql :5455/signals_catalog` apply the `fmp_*_tier0` rows from
   `config/platform/signal-registry.sql`.
3. Gaius: `scripts/warehouse/fmp-fdw.sql` — views read `fmp_*_tier0`
   (`kudu_scan`), not `impala_sql`.
4. Recycle Gaius + Metabase engines. Then `/fmp warehouse AAPL`.

Do not route warehouse models through Gaius `:3100` / `meta.*`.
