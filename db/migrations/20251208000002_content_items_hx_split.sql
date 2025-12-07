-- migrate:up
-- Split content storage: metadata in PostgreSQL, raw content in Iceberg (HX)
--
-- This migration removes the large 'content' column from content_items since
-- raw content is now stored in the Iceberg data lake (gaius.hx). PostgreSQL
-- keeps only metadata for fast queries and the iceberg_id for linking.

-- First, ensure iceberg_id column exists (it should from initial schema)
-- Add index on iceberg_id for efficient joins
CREATE INDEX IF NOT EXISTS idx_content_items_iceberg_id
    ON content_items(iceberg_id)
    WHERE iceberg_id IS NOT NULL;

-- Drop the content column - raw content lives in Iceberg only
-- Note: This is a destructive operation. Any existing content data will be lost.
-- Run a backfill to Iceberg before applying this migration if needed.
ALTER TABLE content_items DROP COLUMN IF EXISTS content;

-- Add a comment explaining the architecture
COMMENT ON TABLE content_items IS
'Content metadata (PostgreSQL) - raw content stored in Iceberg via iceberg_id link.
See gaius.hx module for Iceberg access.';

COMMENT ON COLUMN content_items.iceberg_id IS
'UUID linking to raw.content table in Iceberg data lake (gaius.hx)';

COMMENT ON COLUMN content_items.iceberg_snapshot_id IS
'Iceberg snapshot ID when content was written, for time-travel queries';

-- migrate:down
-- Re-add the content column (data will be lost)
ALTER TABLE content_items ADD COLUMN IF NOT EXISTS content text;

DROP INDEX IF EXISTS idx_content_items_iceberg_id;
