# Gaius as federated FMP SDK; Kudu+Iceberg as SoR

AgentRTC FMP hops were a thin FmpHint projection (name/exchange/snippet).
Gaius already fetched richer quote/eod payloads. Those rows now flatten
into `fmp_quote_tier0` / `fmp_eod_tier0` (with existing profile/filings/
earnings). Iceberg `gaius.fmp.*` remains the best-effort copy.

ServerQuery FMP:

1. `eod`/`price` — recall warehouse first (last week's SLB numbers).
2. Live FMP when the warehouse is empty.
3. Persist every live fetch (fail-soft).
4. Wire to Hermes stays a projection; SoR is Kudu.

Apply path unchanged: `signals_kudu_create` then
`gaius scripts/warehouse/fmp-fdw.sql` on :5444. Do not year-backfill;
ingest is persist-on-query.
