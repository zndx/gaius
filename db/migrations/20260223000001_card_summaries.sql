-- Card summaries: dual-model AI summaries for individual card pages
-- Mirrors collection_summaries table structure

CREATE TABLE IF NOT EXISTS collections.card_summaries (
    summary_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    card_id TEXT NOT NULL REFERENCES collections.cards(card_id) ON DELETE CASCADE,
    summary_type TEXT NOT NULL CHECK (summary_type IN ('frontier', 'open_weights')),
    hx_generation_id TEXT NOT NULL,
    summary_text TEXT NOT NULL,
    model_label TEXT NOT NULL DEFAULT 'frontier model',
    brave_followups JSONB,  -- Array of follow-up query strings (frontier only)
    input_tokens INTEGER,
    output_tokens INTEGER,
    generated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(card_id, summary_type)
);

CREATE INDEX idx_card_summaries_card ON collections.card_summaries(card_id);

GRANT SELECT, INSERT, UPDATE, DELETE ON collections.card_summaries TO gaius;
