-- migrate:up
-- Cognition buffer + forward agenda. HX llm.generations holds full traces.

CREATE TABLE IF NOT EXISTS public.cognition_buffer (
    id BIGSERIAL PRIMARY KEY,
    episode_id TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('slice', 'synthesis')),
    source TEXT NOT NULL,
    content TEXT NOT NULL,
    hx_generation_id TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS cognition_buffer_episode_idx
    ON public.cognition_buffer (episode_id);
CREATE INDEX IF NOT EXISTS cognition_buffer_created_idx
    ON public.cognition_buffer (created_at DESC);

CREATE TABLE IF NOT EXISTS public.agenda_entries (
    id BIGSERIAL PRIMARY KEY,
    kind TEXT NOT NULL CHECK (kind IN ('brief', 'reminder', 'session')),
    title TEXT NOT NULL,
    body TEXT NOT NULL DEFAULT '',
    due_at TIMESTAMPTZ,
    episode_id TEXT NOT NULL,
    hx_generation_id TEXT,
    status TEXT NOT NULL DEFAULT 'open'
        CHECK (status IN ('open', 'done', 'cancelled')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS agenda_entries_open_idx
    ON public.agenda_entries (status, created_at DESC);
CREATE INDEX IF NOT EXISTS agenda_entries_episode_idx
    ON public.agenda_entries (episode_id);

COMMENT ON TABLE public.cognition_buffer IS
    'Incremental synthesis of Publishing + Prospects + Ambient; HX holds traces.';
COMMENT ON TABLE public.agenda_entries IS
    'Forward agenda (brief/reminder/session) curated from cognition_buffer.';

GRANT SELECT, INSERT, UPDATE ON public.cognition_buffer TO gaius;
GRANT SELECT, INSERT, UPDATE ON public.agenda_entries TO gaius;
GRANT USAGE, SELECT ON SEQUENCE public.cognition_buffer_id_seq TO gaius;
GRANT USAGE, SELECT ON SEQUENCE public.agenda_entries_id_seq TO gaius;

-- migrate:down
DROP TABLE IF EXISTS public.agenda_entries;
DROP TABLE IF EXISTS public.cognition_buffer;
