-- migrate:up

-- ============================================================================
-- Bases Feature Store: Kudu + Semantic Layer
-- ============================================================================
-- Phase 2: Rename pinot_table to kudu_table (Kudu is the target backend)
-- Phase 3: Add context column for BFO ontology grounding

-- Add kudu_table column (replacing pinot_table semantically)
ALTER TABLE bases.bases ADD COLUMN IF NOT EXISTS kudu_table TEXT;

-- Add context column for @context JSON-LD style semantic grounding
ALTER TABLE bases.bases ADD COLUMN IF NOT EXISTS context JSONB DEFAULT '{}';

-- Copy existing pinot_table values to kudu_table for backwards compatibility
UPDATE bases.bases SET kudu_table = pinot_table WHERE pinot_table IS NOT NULL AND kudu_table IS NULL;

-- Add comment explaining the semantic layer
COMMENT ON COLUMN bases.bases.context IS 'JSON-LD style @context for BFO ontology grounding';
COMMENT ON COLUMN bases.bases.kudu_table IS 'Kudu table name (via kudu_fdw when available)';

-- migrate:down
ALTER TABLE bases.bases DROP COLUMN IF EXISTS kudu_table;
ALTER TABLE bases.bases DROP COLUMN IF EXISTS context;
