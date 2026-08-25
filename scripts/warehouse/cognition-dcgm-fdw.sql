-- Additive foreign tables for the warehouse products the waterfall reads.
-- Companion to gpu-metrics-fdw.sql; assumes impala_kudu_srv already exists.
--
--   cognition_metrics  narrow (channel, value) waterfall cognition channels
--   gpu_dcgm           narrow (gpu_index, field, value) extended DCGM fields
--
-- tier0 is Kudu (kudu_scan, INSERTable); tier1 is Iceberg and the bare name is
-- the Impala UNION view — both read-only (impala_sql).

DROP FOREIGN TABLE IF EXISTS cognition_metrics CASCADE;
DROP FOREIGN TABLE IF EXISTS cognition_metrics_tier1 CASCADE;
DROP FOREIGN TABLE IF EXISTS cognition_metrics_tier0 CASCADE;
DROP FOREIGN TABLE IF EXISTS gpu_dcgm CASCADE;
DROP FOREIGN TABLE IF EXISTS gpu_dcgm_tier1 CASCADE;
DROP FOREIGN TABLE IF EXISTS gpu_dcgm_tier0 CASCADE;

CREATE FOREIGN TABLE cognition_metrics_tier0 (
  epoch_hour integer,
  ts_ns bigint,
  channel text,
  value double precision,
  present boolean
) SERVER impala_kudu_srv
OPTIONS (
  database 'signals_dataproducts',
  "table" 'cognition_metrics_tier0',
  kudu_table 'impala::signals_dataproducts.cognition_metrics_tier0',
  access 'kudu_scan'
);

CREATE FOREIGN TABLE cognition_metrics_tier1 (
  epoch_hour integer,
  ts_ns bigint,
  channel text,
  value double precision,
  present boolean
) SERVER impala_kudu_srv
OPTIONS (database 'signals_dataproducts', "table" 'cognition_metrics_tier1', access 'impala_sql');

CREATE FOREIGN TABLE cognition_metrics (
  epoch_hour integer,
  ts_ns bigint,
  channel text,
  value double precision,
  present boolean
) SERVER impala_kudu_srv
OPTIONS (database 'signals_dataproducts', "table" 'cognition_metrics', access 'impala_sql');

CREATE FOREIGN TABLE gpu_dcgm_tier0 (
  epoch_hour integer,
  ts_ns bigint,
  gpu_index integer,
  field text,
  value double precision
) SERVER impala_kudu_srv
OPTIONS (
  database 'signals_dataproducts',
  "table" 'gpu_dcgm_tier0',
  kudu_table 'impala::signals_dataproducts.gpu_dcgm_tier0',
  access 'kudu_scan'
);

CREATE FOREIGN TABLE gpu_dcgm_tier1 (
  epoch_hour integer,
  ts_ns bigint,
  gpu_index integer,
  field text,
  value double precision
) SERVER impala_kudu_srv
OPTIONS (database 'signals_dataproducts', "table" 'gpu_dcgm_tier1', access 'impala_sql');

CREATE FOREIGN TABLE gpu_dcgm (
  epoch_hour integer,
  ts_ns bigint,
  gpu_index integer,
  field text,
  value double precision
) SERVER impala_kudu_srv
OPTIONS (database 'signals_dataproducts', "table" 'gpu_dcgm', access 'impala_sql');
