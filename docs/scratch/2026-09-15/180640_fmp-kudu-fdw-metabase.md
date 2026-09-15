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

## Apply

1. Signals: `python -m signals.ops schema-apply` (HS2 CREATE … STORED AS KUDU;
   plain scalars, not `signals_kudu_create.cc`).
2. Gaius: `scripts/warehouse/install_impala_fdw.sh` now also applies
   `scripts/warehouse/fmp-fdw.sql` (`warehouse.v_fmp_profile|filings|earnings`).
3. Recycle Gaius + Metabase engines so PrepareFmpWarehouse / ProjectWarehouse
   load. Then `/fmp warehouse AAPL` (or MCP `fmp_prepare_warehouse`).

Do not route warehouse models through Gaius `:3100` / `meta.*`.
