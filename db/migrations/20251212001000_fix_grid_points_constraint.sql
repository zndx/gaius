-- Fix grid_points unique constraint for ColBERT multi-vector embeddings
-- Each document can have multiple chunks, each with a unique embedding_id
-- We need to allow multiple rows per doc_path, but ensure each embedding_id is unique

-- migrate:up
ALTER TABLE grid_points DROP CONSTRAINT IF EXISTS grid_points_snapshot_id_doc_path_key;
ALTER TABLE grid_points ADD CONSTRAINT grid_points_snapshot_id_embedding_id_key UNIQUE (snapshot_id, embedding_id);

-- migrate:down
ALTER TABLE grid_points DROP CONSTRAINT IF EXISTS grid_points_snapshot_id_embedding_id_key;
ALTER TABLE grid_points ADD CONSTRAINT grid_points_snapshot_id_doc_path_key UNIQUE (snapshot_id, doc_path);
