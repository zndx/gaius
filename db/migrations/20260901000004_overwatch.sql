-- migrate:up

-- Overwatch event ledger: every Nautilus trigger firing and judge
-- consultation, append-only. Overwatch NEVER writes healing_events
-- (its sequence_num allocation is single-writer); it links read-only
-- via the forecast sequence_id where relevant. One per engine —
-- federated peers keep their own.

CREATE TABLE overwatch_events (
    id BIGSERIAL PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    trigger_name TEXT NOT NULL,
    scope TEXT NOT NULL,
    detail TEXT NOT NULL,
    snapshot JSONB NOT NULL DEFAULT '{}',
    judge_invoked BOOLEAN NOT NULL DEFAULT FALSE,
    judge_status TEXT,          -- verdict | judge_unavailable | judge_error | budget_exhausted | not_invoked
    judge_verdict JSONB,
    action_taken TEXT NOT NULL DEFAULT 'recorded',
    forecast_id UUID
);

COMMENT ON TABLE overwatch_events IS
    'Nautilus trigger firings + Overwatch judge consultations (ACP+Grok, agent pinned). Append-only; autonomy v1=monitor.';
COMMENT ON COLUMN overwatch_events.judge_status IS
    'verdict = contract-gated JSON parsed; judge_unavailable = grok credentials absent (fail-closed, no thinking fallback); judge_error = malformed output, no action taken.';

CREATE INDEX idx_overwatch_events_created ON overwatch_events (created_at DESC);
CREATE INDEX idx_overwatch_events_trigger ON overwatch_events (trigger_name, created_at DESC);

GRANT SELECT, INSERT ON overwatch_events TO gaius;
GRANT USAGE, SELECT ON SEQUENCE overwatch_events_id_seq TO gaius;

-- migrate:down

DROP TABLE IF EXISTS overwatch_events;
