-- migrate:up
-- 2026-09-07 (user): "provide the Hermes WebRTC agent with access to the Agenda
-- using a similar design paradigm as … `/thoughts` only now for `/agenda` to
-- return a pre-prepared brief-formatted summary of today's Agenda items along
-- with tomorrow and the coming week. This obviously requires our local
-- thinking capability to understand the gist of today's agenda, and make some
-- judgement calls about what to include from tomorrow and the week ahead … the
-- voice agent only needs to call `/agenda` … return the content from specific
-- agenda items … passing the item ID as an argument."
--
-- One row per Agenda Brief a scheduled `agenda_brief` task writes: the written
-- form (body), the plain-speech form for a voice agent (spoken), which Agenda
-- items it covered (item_ids = their note paths), the operator timezone and
-- calendar day it spoke from, and the KB zettel that persisted it (prev/next-
-- linked to the neighbouring agenda briefs — never an Agenda item itself).
-- Served by ServerQuery kind=AGENDA (AgendaHint) and GaiusService/AgendaBrief
-- (/agenda). Append-only by privilege.

CREATE TABLE IF NOT EXISTS agenda_briefs (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    timezone            TEXT NOT NULL DEFAULT 'UTC',
    today               DATE NOT NULL,
    window_start        DATE,
    window_end          DATE,
    item_ids            TEXT[] NOT NULL DEFAULT '{}',
    items_considered    INTEGER NOT NULL DEFAULT 0,
    title               TEXT NOT NULL,
    body                TEXT NOT NULL,
    spoken              TEXT NOT NULL,
    model               TEXT,
    tokens_used         INTEGER,
    generation_context  JSONB,
    note_path           TEXT
);

CREATE INDEX IF NOT EXISTS idx_agenda_briefs_created ON agenda_briefs (created_at DESC);

COMMENT ON TABLE agenda_briefs IS
    'Agenda Briefs written by the agenda_brief scheduled class: the gist of today, what from tomorrow and the coming week matters, in the operator timezone — ready for /agenda and the Hermes voice agent. Not an Agenda item. Append-only.';
COMMENT ON COLUMN agenda_briefs.timezone IS 'IANA zone the brief speaks in (today/tomorrow/week are calendar days in this zone).';
COMMENT ON COLUMN agenda_briefs.today IS 'The calendar day the brief treated as today.';
COMMENT ON COLUMN agenda_briefs.window_start IS 'Earliest calendar day considered (past-but-open reminders).';
COMMENT ON COLUMN agenda_briefs.window_end IS 'Latest calendar day considered (today + 7).';
COMMENT ON COLUMN agenda_briefs.item_ids IS 'Agenda item ids (their KB note paths) the brief covered — the index a conversational agent uses for follow-ups.';
COMMENT ON COLUMN agenda_briefs.body IS 'The written Brief (≤ ~1400 chars): today''s gist, what from tomorrow matters, what in the week deserves attention; items referred to by title.';
COMMENT ON COLUMN agenda_briefs.spoken IS 'The same for a voice agent: plain speech, no markdown/lists/links (≤ ~800 chars).';
COMMENT ON COLUMN agenda_briefs.generation_context IS 'Prompt/parse provenance: budget, response length, bucket counts.';
COMMENT ON COLUMN agenda_briefs.note_path IS 'KB zettel (relative to the KB root) that persisted this brief, prev/next-linked to the previous/next agenda brief note.';

GRANT SELECT, INSERT ON agenda_briefs TO gaius;

-- The scheduled class: every 4 h, offset from cognition-periodic (:43 at
-- 0,4,8,…) so the two thinking-lane briefs never queue behind each other.
-- Singleton: one live row per class (the guard the other classes use).
SELECT cron.unschedule('agenda-brief') WHERE EXISTS (SELECT 1 FROM cron.job WHERE jobname = 'agenda-brief');
SELECT cron.schedule(
    'agenda-brief',
    '13 1,5,9,13,17,21 * * *',
    $$INSERT INTO scheduled_tasks (task_type, payload, source, scheduled_for)
      SELECT 'agenda_brief', '{}'::jsonb, 'pg_cron', NOW()
      WHERE NOT EXISTS (
        SELECT 1 FROM scheduled_tasks
        WHERE task_type = 'agenda_brief' AND completed_at IS NULL
      )$$
);

-- migrate:down
SELECT cron.unschedule('agenda-brief') WHERE EXISTS (SELECT 1 FROM cron.job WHERE jobname = 'agenda-brief');
DROP TABLE IF EXISTS agenda_briefs;
