-- FMP warehouse: foreign tables over signals_dataproducts.fmp_* (Kudu tier0
-- + Impala logical views; see signals config/platform/fmp-kudu.sql).
-- Apply to gaius :5444 (Metabase path). impala_kudu_srv must exist
-- (install_impala_fdw.sh). Do not point Metabase at Gaius :3100 meta.*.

DROP FOREIGN TABLE IF EXISTS fmp_profile CASCADE;
DROP FOREIGN TABLE IF EXISTS fmp_profile_tier0 CASCADE;
DROP FOREIGN TABLE IF EXISTS fmp_filings CASCADE;
DROP FOREIGN TABLE IF EXISTS fmp_filings_tier0 CASCADE;
DROP FOREIGN TABLE IF EXISTS fmp_earnings CASCADE;
DROP FOREIGN TABLE IF EXISTS fmp_earnings_tier0 CASCADE;
DROP FOREIGN TABLE IF EXISTS fmp_quote CASCADE;
DROP FOREIGN TABLE IF EXISTS fmp_quote_tier0 CASCADE;
DROP FOREIGN TABLE IF EXISTS fmp_eod CASCADE;
DROP FOREIGN TABLE IF EXISTS fmp_eod_tier0 CASCADE;

CREATE FOREIGN TABLE fmp_profile_tier0 (
  epoch_hour integer,
  ts_ns bigint,
  symbol text,
  name text,
  exchange text,
  sector text,
  industry text,
  market_cap double precision,
  website text,
  description text
) SERVER impala_kudu_srv OPTIONS (
  database 'signals_dataproducts', "table" 'fmp_profile_tier0',
  kudu_table 'impala::signals_dataproducts.fmp_profile_tier0', access 'kudu_scan');

CREATE FOREIGN TABLE fmp_profile (
  epoch_hour integer,
  ts_ns bigint,
  symbol text,
  name text,
  exchange text,
  sector text,
  industry text,
  market_cap double precision,
  website text,
  description text
) SERVER impala_kudu_srv OPTIONS (
  database 'signals_dataproducts', "table" 'fmp_profile', access 'impala_sql');

CREATE FOREIGN TABLE fmp_filings_tier0 (
  epoch_hour integer,
  ts_ns bigint,
  symbol text,
  form text,
  filed text,
  url text
) SERVER impala_kudu_srv OPTIONS (
  database 'signals_dataproducts', "table" 'fmp_filings_tier0',
  kudu_table 'impala::signals_dataproducts.fmp_filings_tier0', access 'kudu_scan');

CREATE FOREIGN TABLE fmp_filings (
  epoch_hour integer,
  ts_ns bigint,
  symbol text,
  form text,
  filed text,
  url text
) SERVER impala_kudu_srv OPTIONS (
  database 'signals_dataproducts', "table" 'fmp_filings', access 'impala_sql');

CREATE FOREIGN TABLE fmp_earnings_tier0 (
  epoch_hour integer,
  ts_ns bigint,
  symbol text,
  announced text,
  eps double precision,
  eps_estimated double precision
) SERVER impala_kudu_srv OPTIONS (
  database 'signals_dataproducts', "table" 'fmp_earnings_tier0',
  kudu_table 'impala::signals_dataproducts.fmp_earnings_tier0', access 'kudu_scan');

CREATE FOREIGN TABLE fmp_earnings (
  epoch_hour integer,
  ts_ns bigint,
  symbol text,
  announced text,
  eps double precision,
  eps_estimated double precision
) SERVER impala_kudu_srv OPTIONS (
  database 'signals_dataproducts', "table" 'fmp_earnings', access 'impala_sql');

CREATE SCHEMA IF NOT EXISTS warehouse;

-- Metabase reads these. Source is kudu_scan tier0 (direct libkudu_client),
-- not impala_sql — no Python impyla, no HS2 on the query path.
CREATE OR REPLACE VIEW warehouse.v_fmp_profile AS
SELECT
  symbol,
  name,
  exchange,
  sector,
  industry,
  market_cap,
  website,
  description,
  to_timestamp(ts_ns / 1e9) AT TIME ZONE 'UTC' AS as_of
FROM fmp_profile_tier0;

CREATE OR REPLACE VIEW warehouse.v_fmp_filings AS
SELECT
  symbol,
  form,
  filed,
  url,
  to_timestamp(ts_ns / 1e9) AT TIME ZONE 'UTC' AS as_of
FROM fmp_filings_tier0;

CREATE OR REPLACE VIEW warehouse.v_fmp_earnings AS
SELECT
  symbol,
  announced,
  eps,
  eps_estimated,
  to_timestamp(ts_ns / 1e9) AT TIME ZONE 'UTC' AS as_of
FROM fmp_earnings_tier0;

CREATE FOREIGN TABLE fmp_quote_tier0 (
  epoch_hour integer,
  ts_ns bigint,
  symbol text,
  name text,
  exchange text,
  price double precision,
  change double precision,
  change_percent double precision,
  volume bigint,
  day_low double precision,
  day_high double precision
) SERVER impala_kudu_srv OPTIONS (
  database 'signals_dataproducts', "table" 'fmp_quote_tier0',
  kudu_table 'impala::signals_dataproducts.fmp_quote_tier0', access 'kudu_scan');

CREATE FOREIGN TABLE fmp_eod_tier0 (
  epoch_hour integer,
  ts_ns bigint,
  symbol text,
  bar_date text,
  open double precision,
  high double precision,
  low double precision,
  close double precision,
  volume bigint
) SERVER impala_kudu_srv OPTIONS (
  database 'signals_dataproducts', "table" 'fmp_eod_tier0',
  kudu_table 'impala::signals_dataproducts.fmp_eod_tier0', access 'kudu_scan');

CREATE OR REPLACE VIEW warehouse.v_fmp_quote AS
SELECT
  symbol,
  name,
  exchange,
  price,
  change,
  change_percent,
  volume,
  day_low,
  day_high,
  to_timestamp(ts_ns / 1e9) AT TIME ZONE 'UTC' AS as_of
FROM fmp_quote_tier0;

CREATE OR REPLACE VIEW warehouse.v_fmp_eod AS
SELECT
  symbol,
  bar_date,
  open,
  high,
  low,
  close,
  volume,
  to_timestamp(ts_ns / 1e9) AT TIME ZONE 'UTC' AS as_of
FROM fmp_eod_tier0;
