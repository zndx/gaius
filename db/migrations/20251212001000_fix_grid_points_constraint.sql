-- Fix grid_points unique constraint for ColBERT multi-vector embeddings
-- Each document can have multiple chunks, each with a unique embedding_id
-- We need to allow multiple rows per doc_path, but ensure each embedding_id is unique

-- migrate:up
-- This host never created grid_points (ColBERT path unused). No-op when
-- the table is absent so later pending migrations can apply.
DO $$
BEGIN
  IF to_regclass('public.grid_points') IS NOT NULL THEN
    ALTER TABLE grid_points DROP CONSTRAINT IF EXISTS grid_points_snapshot_id_doc_path_key;
    ALTER TABLE grid_points ADD CONSTRAINT grid_points_snapshot_id_embedding_id_key UNIQUE (snapshot_id, embedding_id);
  END IF;
END $$;

-- migrate:down
ALTER TABLE grid_points DROP CONSTRAINT IF EXISTS grid_points_snapshot_id_embedding_id_key;
ALTER TABLE grid_points ADD CONSTRAINT grid_points_snapshot_id_doc_path_key UNIQUE (snapshot_id, doc_path);
