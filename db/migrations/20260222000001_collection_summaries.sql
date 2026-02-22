-- migrate:up

-- ============================================================================
-- Collection Summaries
-- ============================================================================
-- Stores AI-generated collection summaries (dual-model: frontier + open-weights).
-- Full LLM output lives in Iceberg HX; this table holds denormalized text
-- for fast KV sync and the Iceberg reference for full provenance.

CREATE TABLE collections.collection_summaries (
    summary_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    collection_id TEXT NOT NULL REFERENCES collections.collections(collection_id) ON DELETE CASCADE,
    summary_type TEXT NOT NULL CHECK (summary_type IN ('frontier', 'open_weights')),

    -- Reference to Iceberg HX record (source of truth for full content)
    hx_generation_id TEXT NOT NULL,

    -- Denormalized summary text for fast KV sync (avoids Iceberg read on every sync)
    summary_text TEXT NOT NULL,

    -- Public-facing label (never exposes internal model names)
    model_label TEXT NOT NULL DEFAULT 'frontier model',

    -- Generation metadata
    input_tokens INTEGER,
    output_tokens INTEGER,
    generated_at TIMESTAMPTZ DEFAULT NOW(),

    -- Only one summary per type per collection
    UNIQUE(collection_id, summary_type)
);

CREATE INDEX idx_collection_summaries_collection
    ON collections.collection_summaries(collection_id);

COMMENT ON TABLE collections.collection_summaries
    IS 'AI-generated collection summaries with dual-model perspectives';
COMMENT ON COLUMN collections.collection_summaries.hx_generation_id
    IS 'Reference to Iceberg HX llm.generations record for full provenance';
COMMENT ON COLUMN collections.collection_summaries.model_label
    IS 'Public-facing label - never expose internal model identifiers';

-- ============================================================================
-- Zettle slug tracking on cards
-- ============================================================================
-- Each card records the zettle-slug that was current when the card was added.
-- As the collection topic centroid evolves, new cards get the latest slug
-- while old cards retain their original.

ALTER TABLE collections.cards
    ADD COLUMN IF NOT EXISTS zettle_slug TEXT;

COMMENT ON COLUMN collections.cards.zettle_slug
    IS 'Zettelkasten slug current when card was created (human-readable alias)';

CREATE INDEX idx_cards_zettle_slug
    ON collections.cards(zettle_slug)
    WHERE zettle_slug IS NOT NULL;

-- ============================================================================
-- Grants
-- ============================================================================

GRANT SELECT, INSERT, UPDATE, DELETE ON collections.collection_summaries TO gaius;

-- migrate:down

DROP TABLE IF EXISTS collections.collection_summaries;
ALTER TABLE collections.cards DROP COLUMN IF EXISTS zettle_slug;
