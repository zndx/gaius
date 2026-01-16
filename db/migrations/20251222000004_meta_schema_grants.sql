-- migrate:up

-- Grant gaius user access to meta schema for MetaAgent analytics queries
-- This was missing from the original meta_schema migration

-- Grant schema usage
GRANT USAGE ON SCHEMA meta TO gaius;

-- Grant SELECT on all existing tables
GRANT SELECT ON ALL TABLES IN SCHEMA meta TO gaius;

-- Grant INSERT/UPDATE for MetaSyncFlow operations
GRANT INSERT, UPDATE ON ALL TABLES IN SCHEMA meta TO gaius;

-- Grant USAGE on sequences for INSERT operations
GRANT USAGE ON ALL SEQUENCES IN SCHEMA meta TO gaius;

-- Set default privileges for future tables created in meta schema
ALTER DEFAULT PRIVILEGES IN SCHEMA meta GRANT SELECT, INSERT, UPDATE ON TABLES TO gaius;
ALTER DEFAULT PRIVILEGES IN SCHEMA meta GRANT USAGE ON SEQUENCES TO gaius;

-- migrate:down

-- Revoke all privileges from gaius on meta schema
REVOKE ALL ON ALL TABLES IN SCHEMA meta FROM gaius;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA meta FROM gaius;
REVOKE USAGE ON SCHEMA meta FROM gaius;
ALTER DEFAULT PRIVILEGES IN SCHEMA meta REVOKE ALL ON TABLES FROM gaius;
ALTER DEFAULT PRIVILEGES IN SCHEMA meta REVOKE ALL ON SEQUENCES FROM gaius;
