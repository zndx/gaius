-- Gaius zndx_gaius → system Impala HS2 / Kudu (same servers Signals uses).
-- Do not DROP Signals :5455 objects. This is a second FDW client.
-- Placeholders: __FDW_SO__  __KEYTAB__  __HS2_HOST__  __KUDU_MASTERS__

DROP FOREIGN TABLE IF EXISTS gpu_metrics CASCADE;
DROP FOREIGN TABLE IF EXISTS gpu_metrics_tier1 CASCADE;
DROP FOREIGN TABLE IF EXISTS gpu_metrics_tier0 CASCADE;
DROP USER MAPPING IF EXISTS FOR CURRENT_USER SERVER impala_kudu_srv;
DROP USER MAPPING IF EXISTS FOR gaius SERVER impala_kudu_srv;
DROP SERVER IF EXISTS impala_kudu_srv CASCADE;

DROP FOREIGN DATA WRAPPER IF EXISTS impala_fdw CASCADE;
DROP FUNCTION IF EXISTS impala_fdw_handler() CASCADE;
DROP FUNCTION IF EXISTS impala_fdw_validator(text[], oid) CASCADE;
DROP FUNCTION IF EXISTS impala_fdw_exec(text, text) CASCADE;

CREATE FUNCTION impala_fdw_handler()
RETURNS fdw_handler
AS '__FDW_SO__'
LANGUAGE C STRICT;

CREATE FUNCTION impala_fdw_validator(text[], oid)
RETURNS void
AS '__FDW_SO__'
LANGUAGE C STRICT;

CREATE FOREIGN DATA WRAPPER impala_fdw
  HANDLER impala_fdw_handler
  VALIDATOR impala_fdw_validator;

CREATE FUNCTION impala_fdw_exec(server_name text, sql text)
RETURNS text
AS '__FDW_SO__'
LANGUAGE C STRICT;

CREATE SERVER impala_kudu_srv
  FOREIGN DATA WRAPPER impala_fdw
  OPTIONS (
    host '__HS2_HOST__',
    port '21050',
    auth 'kerberos',
    kudu_masters '__KUDU_MASTERS__',
    default_access 'auto'
  );

CREATE USER MAPPING IF NOT EXISTS FOR CURRENT_USER SERVER impala_kudu_srv
  OPTIONS (
    principal 'signals@DEV.VISTA.ZNDX.ORG',
    keytab '__KEYTAB__'
  );
CREATE USER MAPPING IF NOT EXISTS FOR gaius SERVER impala_kudu_srv
  OPTIONS (
    principal 'signals@DEV.VISTA.ZNDX.ORG',
    keytab '__KEYTAB__'
  );

CREATE FOREIGN TABLE gpu_metrics_tier0 (
  epoch_hour integer,
  ts_ns bigint,
  gpu_index integer,
  power_w real,
  util_pct real,
  mem_used_mb real,
  temp_c real
) SERVER impala_kudu_srv
OPTIONS (
  database 'signals_dataproducts',
  "table" 'gpu_metrics_tier0',
  kudu_table 'impala::signals_dataproducts.gpu_metrics_tier0',
  access 'kudu_scan'
);

CREATE FOREIGN TABLE gpu_metrics_tier1 (
  epoch_hour integer,
  ts_ns bigint,
  gpu_index integer,
  power_w real,
  util_pct real,
  mem_used_mb real,
  temp_c real
) SERVER impala_kudu_srv
OPTIONS (
  database 'signals_dataproducts',
  "table" 'gpu_metrics_tier1',
  access 'impala_sql'
);

CREATE FOREIGN TABLE gpu_metrics (
  epoch_hour integer,
  ts_ns bigint,
  gpu_index integer,
  power_w real,
  util_pct real,
  mem_used_mb real,
  temp_c real
) SERVER impala_kudu_srv
OPTIONS (
  database 'signals_dataproducts',
  "table" 'gpu_metrics',
  access 'impala_sql'
);

GRANT SELECT, INSERT ON gpu_metrics_tier0 TO gaius;
GRANT SELECT ON gpu_metrics_tier1 TO gaius;
GRANT SELECT ON gpu_metrics TO gaius;
GRANT EXECUTE ON FUNCTION impala_fdw_exec(text, text) TO gaius;
