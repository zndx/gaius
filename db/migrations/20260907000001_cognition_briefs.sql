-- migrate:up
-- 2026-09-07 (user): "the default for /thoughts should be a brief summary of
-- recent thoughts, using the same sort of framing as we'd use for our Agenda
-- … enhance the autonomous cognition cycle to create this Brief as part of the
-- normal workflow so /thoughts already has the reply ready, for an instant
-- return to the voice agent." And: NOT an Agenda item — "we want multiple
-- sources of content for conversation — the thoughts brief should be a Zettle
-- with prev and next links like our other thoughts."
--
-- One row per Brief the cognition cycle writes: the written form (body), the
-- plain-speech form for a voice agent (spoken), which thoughts it considered,
-- and the KB note that persisted it (prev/next-linked like thoughts_cycle
-- notes). Served by ServerQuery kind=THOUGHTS (ThoughtsHint.brief/spoken) and
-- GaiusService/ThoughtsBrief (/thoughts). Append-only by privilege.

CREATE TABLE IF NOT EXISTS cognition_briefs (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    cycle_id            UUID,
    window_start        TIMESTAMPTZ,
    window_end          TIMESTAMPTZ,
    thought_ids         UUID[] NOT NULL DEFAULT '{}',
    thoughts_considered INTEGER NOT NULL DEFAULT 0,
    title               TEXT NOT NULL,
    body                TEXT NOT NULL,
    spoken              TEXT NOT NULL,
    model               TEXT,
    tokens_used         INTEGER,
    generation_context  JSONB,
    note_path           TEXT
);

CREATE INDEX IF NOT EXISTS idx_cognition_briefs_created ON cognition_briefs (created_at DESC);

COMMENT ON TABLE cognition_briefs IS
    'Thoughts Briefs written by the cognition cycle (Agenda-LIKE framing, never an Agenda item): what the cognition has been thinking about, ready for /thoughts and the Hermes voice agent. Append-only.';
COMMENT ON COLUMN cognition_briefs.cycle_id IS 'The cognition_cycles row (or task) that produced it; NULL for a brief composed by hand (/thoughts cycle, scripts).';
COMMENT ON COLUMN cognition_briefs.window_start IS 'Oldest thought considered.';
COMMENT ON COLUMN cognition_briefs.window_end IS 'Newest thought considered (the brief is current as of this).';
COMMENT ON COLUMN cognition_briefs.thought_ids IS 'cognition_thoughts.id of every thought the brief summarises.';
COMMENT ON COLUMN cognition_briefs.body IS 'The written Brief (≤ ~1200 chars): first person, what is on the mind, the lines of thought and their connections, open questions, what to attend to next.';
COMMENT ON COLUMN cognition_briefs.spoken IS 'The same for a voice agent: plain speech, 4–6 sentences, no markdown/lists/links/code (≤ ~700 chars).';
COMMENT ON COLUMN cognition_briefs.generation_context IS 'Prompt/parse provenance: budget, response length, parse notes.';
COMMENT ON COLUMN cognition_briefs.note_path IS 'KB zettel (relative to the KB root) that persisted this brief, prev/next-linked to the previous/next brief note.';

GRANT SELECT, INSERT ON cognition_briefs TO gaius;

-- migrate:down
DROP TABLE IF EXISTS cognition_briefs;
