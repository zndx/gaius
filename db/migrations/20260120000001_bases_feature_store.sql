-- migrate:up

-- ============================================================================
-- Feature Store Registry Schema
-- ============================================================================
-- Stores feature definitions, base metadata, and Iceberg catalog references.
-- This is the "control plane" - Iceberg/Pinot are the "data plane".
--
-- Inspired by Obsidian Dataview semantics: data exposed through named "Bases"
-- that abstract away the underlying storage (PostgreSQL, Iceberg, Pinot).

CREATE SCHEMA IF NOT EXISTS bases;
COMMENT ON SCHEMA bases IS 'Feature store registry and Iceberg catalog';

-- ============================================================================
-- Entity Definitions
-- ============================================================================

-- Entity types (user, transaction, device, etc.)
CREATE TABLE bases.entity_types (
    entity_type_id TEXT PRIMARY KEY,           -- e.g., "user", "transaction"
    display_name TEXT NOT NULL,
    description TEXT,
    key_columns JSONB NOT NULL,                -- [{"name": "user_id", "type": "STRING"}]
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

COMMENT ON TABLE bases.entity_types IS 'Entity types that features can be computed for';

-- ============================================================================
-- Feature Definitions
-- ============================================================================

-- Feature groups (logical groupings like "user_profile", "transaction_risk")
CREATE TABLE bases.feature_groups (
    group_id TEXT PRIMARY KEY,                 -- e.g., "user_profile"
    display_name TEXT NOT NULL,
    description TEXT,
    entity_type_id TEXT REFERENCES bases.entity_types(entity_type_id),
    owner TEXT,                                -- Team/person responsible
    tags TEXT[] DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_bases_fg_entity ON bases.feature_groups(entity_type_id);
CREATE INDEX idx_bases_fg_tags ON bases.feature_groups USING GIN(tags);

-- Individual feature definitions
CREATE TABLE bases.features (
    feature_id TEXT PRIMARY KEY,               -- e.g., "user_profile.age"
    group_id TEXT NOT NULL REFERENCES bases.feature_groups(group_id),
    name TEXT NOT NULL,                        -- Short name: "age"
    display_name TEXT,
    description TEXT,

    -- Type information (Arrow-compatible)
    value_type TEXT NOT NULL,                  -- STRING, INT64, FLOAT64, BOOLEAN, TIMESTAMP, ARRAY<T>, STRUCT<...>
    nullable BOOLEAN DEFAULT true,
    default_value JSONB,                       -- Default if missing

    -- Computation metadata
    transformation TEXT,                       -- SQL/expression to compute
    aggregation_type TEXT,                     -- For time-window features: SUM, AVG, COUNT, etc.
    window_duration INTERVAL,                  -- For time-window features

    -- Lifecycle
    status TEXT DEFAULT 'active',              -- active, deprecated, archived
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE(group_id, name)
);

CREATE INDEX idx_bases_features_group ON bases.features(group_id);
CREATE INDEX idx_bases_features_status ON bases.features(status);

-- ============================================================================
-- Base Definitions
-- ============================================================================

-- Base types
CREATE TYPE bases.base_type AS ENUM ('snapshot', 'historical', 'registry');

-- Base definitions (the core abstraction)
CREATE TABLE bases.bases (
    base_id TEXT PRIMARY KEY,                  -- e.g., "user_features"
    display_name TEXT NOT NULL,
    description TEXT,
    base_type bases.base_type NOT NULL,

    -- Schema definition (columns exposed by this base)
    schema JSONB NOT NULL,                     -- [{name, type, nullable, description}]

    -- Source binding
    source_entity_type TEXT REFERENCES bases.entity_types(entity_type_id),
    source_feature_groups TEXT[],              -- Which feature groups to pull from

    -- Physical binding (which backend to query)
    physical_table TEXT,                       -- Iceberg table or Pinot table name
    pinot_table TEXT,                          -- For snapshot bases: Pinot table

    -- Default query parameters
    default_dql TEXT,                          -- Default filter/sort (Dataview-style)
    default_time_range INTERVAL DEFAULT '7 days',  -- For historical bases
    max_time_range INTERVAL DEFAULT '90 days',     -- Guardrail

    -- Access control
    read_acl TEXT[] DEFAULT '{"*"}',           -- Who can read (* = all)

    -- Metadata
    owner TEXT,
    tags TEXT[] DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_bases_bases_type ON bases.bases(base_type);
CREATE INDEX idx_bases_bases_entity ON bases.bases(source_entity_type);

-- ============================================================================
-- Iceberg Catalog (minimal - PyIceberg handles most)
-- ============================================================================

-- Track Iceberg tables registered with this feature store
CREATE TABLE bases.iceberg_tables (
    table_id TEXT PRIMARY KEY,                 -- Fully qualified: namespace.table_name
    namespace TEXT NOT NULL,                   -- e.g., "features", "events"
    table_name TEXT NOT NULL,
    location TEXT NOT NULL,                    -- s3://... or file://...

    -- Schema info (cached from Iceberg metadata)
    current_schema_id INTEGER,
    partition_spec JSONB,
    sort_order JSONB,

    -- Stats
    record_count BIGINT,
    file_count INTEGER,
    total_size_bytes BIGINT,

    -- Lifecycle
    last_commit_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE(namespace, table_name)
);

CREATE INDEX idx_bases_iceberg_ns ON bases.iceberg_tables(namespace);

-- ============================================================================
-- Lineage
-- ============================================================================

-- Track feature dependencies (for impact analysis)
CREATE TABLE bases.feature_lineage (
    id SERIAL PRIMARY KEY,
    source_feature_id TEXT REFERENCES bases.features(feature_id),
    target_feature_id TEXT REFERENCES bases.features(feature_id),
    relationship TEXT DEFAULT 'derived_from',   -- derived_from, aggregates, transforms
    transformation TEXT,                        -- Expression/SQL
    created_at TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE(source_feature_id, target_feature_id)
);

CREATE INDEX idx_bases_lineage_source ON bases.feature_lineage(source_feature_id);
CREATE INDEX idx_bases_lineage_target ON bases.feature_lineage(target_feature_id);

-- ============================================================================
-- Query Audit Log (for guardrails)
-- ============================================================================

CREATE TABLE bases.query_log (
    id BIGSERIAL PRIMARY KEY,
    base_id TEXT REFERENCES bases.bases(base_id),
    dql_query TEXT NOT NULL,
    compiled_sql TEXT,
    backend TEXT,                              -- postgres, iceberg, pinot
    executed_at TIMESTAMPTZ DEFAULT NOW(),
    duration_ms INTEGER,
    rows_returned INTEGER,
    client_id TEXT,                            -- MCP client identifier
    error TEXT                                 -- NULL if successful
);

CREATE INDEX idx_bases_qlog_base ON bases.query_log(base_id, executed_at DESC);
CREATE INDEX idx_bases_qlog_time ON bases.query_log(executed_at DESC);

-- ============================================================================
-- Seed Data: Registry Bases (self-documenting)
-- ============================================================================

-- Entity type for registry metadata
INSERT INTO bases.entity_types (entity_type_id, display_name, description, key_columns)
VALUES ('registry', 'Registry', 'Feature store registry metadata', '[{"name": "id", "type": "STRING"}]');

-- Registry bases (query the registry itself)
INSERT INTO bases.bases (base_id, display_name, description, base_type, schema, source_entity_type, physical_table)
VALUES
    ('_entity_types', 'Entity Types', 'Available entity types in the feature store', 'registry',
     '[{"name": "entity_type_id", "type": "STRING", "nullable": false},
       {"name": "display_name", "type": "STRING", "nullable": false},
       {"name": "description", "type": "STRING", "nullable": true},
       {"name": "key_columns", "type": "STRUCT", "nullable": false}]',
     'registry', 'bases.entity_types'),

    ('_feature_groups', 'Feature Groups', 'Feature groups organizing related features', 'registry',
     '[{"name": "group_id", "type": "STRING", "nullable": false},
       {"name": "display_name", "type": "STRING", "nullable": false},
       {"name": "entity_type_id", "type": "STRING", "nullable": true},
       {"name": "owner", "type": "STRING", "nullable": true},
       {"name": "tags", "type": "ARRAY<STRING>", "nullable": true}]',
     'registry', 'bases.feature_groups'),

    ('_features', 'Features', 'Individual feature definitions', 'registry',
     '[{"name": "feature_id", "type": "STRING", "nullable": false},
       {"name": "group_id", "type": "STRING", "nullable": false},
       {"name": "name", "type": "STRING", "nullable": false},
       {"name": "value_type", "type": "STRING", "nullable": false},
       {"name": "status", "type": "STRING", "nullable": false}]',
     'registry', 'bases.features'),

    ('_bases', 'Bases', 'Available data Bases', 'registry',
     '[{"name": "base_id", "type": "STRING", "nullable": false},
       {"name": "display_name", "type": "STRING", "nullable": false},
       {"name": "base_type", "type": "STRING", "nullable": false},
       {"name": "source_entity_type", "type": "STRING", "nullable": true}]',
     'registry', 'bases.bases');

-- ============================================================================
-- Grants
-- ============================================================================

GRANT USAGE ON SCHEMA bases TO gaius;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA bases TO gaius;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA bases TO gaius;

-- migrate:down
DROP SCHEMA IF EXISTS bases CASCADE;
