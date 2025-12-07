-- migrate:up

-- Cognition Memory: Thoughts, Sessions, and Research Threads
-- Enables Gaius to answer "What have you been thinking about?"

-- ═══════════════════════════════════════════════════════════════════════════════
-- Cognition Thoughts: The thought stream from background thinking
-- ═══════════════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS cognition_thoughts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Classification
    thought_type TEXT NOT NULL,  -- pattern, connection, curiosity, momentum, observation, synthesis
    status TEXT NOT NULL DEFAULT 'active',  -- active, surfaced, acknowledged, stale, archived

    -- Content
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    summary TEXT,  -- 1-2 sentence version for greeting

    -- Relationships
    domains TEXT[] DEFAULT '{}',
    kb_paths TEXT[] DEFAULT '{}',
    source_entries TEXT[] DEFAULT '{}',  -- Content items that triggered this
    related_thoughts UUID[] DEFAULT '{}',

    -- Scoring (0.0 - 1.0)
    salience FLOAT DEFAULT 0.5,    -- How important/interesting
    confidence FLOAT DEFAULT 0.5,  -- How confident in the observation
    novelty FLOAT DEFAULT 0.5,     -- How new/surprising

    -- Timestamps
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    surfaced_at TIMESTAMPTZ,       -- When shown to user
    expires_at TIMESTAMPTZ,        -- Auto-archive after

    -- Generation metadata
    profile_name TEXT DEFAULT 'default',
    generator_model TEXT,
    tokens_used INTEGER DEFAULT 0,
    generation_context JSONB DEFAULT '{}'
);

-- Indexes for efficient querying
CREATE INDEX IF NOT EXISTS idx_thoughts_active
    ON cognition_thoughts(salience DESC, created_at DESC)
    WHERE status = 'active';

CREATE INDEX IF NOT EXISTS idx_thoughts_type
    ON cognition_thoughts(thought_type);

CREATE INDEX IF NOT EXISTS idx_thoughts_domains
    ON cognition_thoughts USING GIN(domains);

CREATE INDEX IF NOT EXISTS idx_thoughts_profile
    ON cognition_thoughts(profile_name, created_at DESC);

-- ═══════════════════════════════════════════════════════════════════════════════
-- Sessions: Track user sessions for continuity
-- ═══════════════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    profile_name TEXT NOT NULL DEFAULT 'default',

    -- Lifecycle
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ended_at TIMESTAMPTZ,
    duration_seconds INTEGER,  -- Computed on close

    -- Context
    initial_domain TEXT,
    final_domain TEXT,

    -- Captured state at session end
    open_threads JSONB DEFAULT '[]',  -- Unfinished research threads
    key_topics JSONB DEFAULT '[]',    -- Topics explored this session
    research_notes TEXT,              -- Auto-generated notes

    -- Metrics
    metrics JSONB DEFAULT '{}',
    -- {queries, swarm_runs, kb_entries, domains_visited, tokens_used}

    -- Handoff
    handoff_generated BOOLEAN DEFAULT FALSE,
    handoff_summary TEXT,  -- LLM-generated session summary
    handoff_kb_path TEXT   -- Path to Zettelkasten note if persisted
);

CREATE INDEX IF NOT EXISTS idx_sessions_profile
    ON sessions(profile_name, started_at DESC);

CREATE INDEX IF NOT EXISTS idx_sessions_recent
    ON sessions(started_at DESC)
    WHERE ended_at IS NOT NULL;

-- ═══════════════════════════════════════════════════════════════════════════════
-- Research Threads: Persistent open investigations across sessions
-- ═══════════════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS research_threads (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    profile_name TEXT NOT NULL DEFAULT 'default',

    -- Thread identity
    topic TEXT NOT NULL,
    domain TEXT,
    status TEXT NOT NULL DEFAULT 'active',  -- active, paused, completed, abandoned
    priority TEXT DEFAULT 'normal',         -- high, normal, low

    -- Content
    initial_query TEXT,
    goal TEXT,
    current_focus TEXT,

    -- Accumulated work
    queries JSONB DEFAULT '[]',      -- [{query, timestamp, results_count}]
    kb_entries TEXT[] DEFAULT '{}',  -- Paths to related KB entries
    insights JSONB DEFAULT '[]',     -- Key findings so far
    next_steps TEXT,                 -- What to do next

    -- Tracking
    query_count INTEGER DEFAULT 0,
    entry_count INTEGER DEFAULT 0,
    swarm_run_count INTEGER DEFAULT 0,

    -- Timestamps
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_activity TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Session link
    created_session_id UUID REFERENCES sessions(id),
    last_session_id UUID REFERENCES sessions(id)
);

CREATE INDEX IF NOT EXISTS idx_threads_active
    ON research_threads(profile_name, last_activity DESC)
    WHERE status = 'active';

CREATE INDEX IF NOT EXISTS idx_threads_domain
    ON research_threads(domain)
    WHERE status = 'active';

-- ═══════════════════════════════════════════════════════════════════════════════
-- User Interests: Learned preferences over time
-- ═══════════════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS user_interests (
    id SERIAL PRIMARY KEY,
    profile_name TEXT NOT NULL DEFAULT 'default',

    -- Interest identification
    topic TEXT NOT NULL,
    domain TEXT,

    -- Activity metrics
    query_count INTEGER DEFAULT 0,
    kb_entry_count INTEGER DEFAULT 0,
    swarm_run_count INTEGER DEFAULT 0,
    session_count INTEGER DEFAULT 0,
    total_time_seconds INTEGER DEFAULT 0,

    -- Scoring
    interest_score FLOAT DEFAULT 0.0,  -- Computed from activity + recency

    -- Timestamps
    first_seen TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_activity TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE (profile_name, topic)
);

CREATE INDEX IF NOT EXISTS idx_interests_score
    ON user_interests(profile_name, interest_score DESC);

-- ═══════════════════════════════════════════════════════════════════════════════
-- Cognition Cycles: Track when cognition runs
-- ═══════════════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS cognition_cycles (
    id SERIAL PRIMARY KEY,
    profile_name TEXT NOT NULL DEFAULT 'default',

    -- Timing
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    duration_ms INTEGER,

    -- Trigger
    trigger_reason TEXT NOT NULL,  -- scheduled, content_threshold, session_start, manual

    -- Results
    thoughts_generated INTEGER DEFAULT 0,
    patterns_detected INTEGER DEFAULT 0,
    connections_found INTEGER DEFAULT 0,

    -- Resources
    model_used TEXT,
    tokens_used INTEGER DEFAULT 0,

    -- Context
    content_items_analyzed INTEGER DEFAULT 0,
    kb_entries_scanned INTEGER DEFAULT 0,

    -- Errors
    error TEXT,
    success BOOLEAN DEFAULT TRUE
);

CREATE INDEX IF NOT EXISTS idx_cycles_recent
    ON cognition_cycles(profile_name, started_at DESC);

-- ═══════════════════════════════════════════════════════════════════════════════
-- Helper Functions
-- ═══════════════════════════════════════════════════════════════════════════════

-- Get time since last cognition cycle
CREATE OR REPLACE FUNCTION time_since_last_cognition(p_profile TEXT DEFAULT 'default')
RETURNS INTERVAL AS $$
    SELECT COALESCE(
        NOW() - (
            SELECT completed_at
            FROM cognition_cycles
            WHERE profile_name = p_profile
              AND success = TRUE
            ORDER BY completed_at DESC
            LIMIT 1
        ),
        INTERVAL '999 days'
    );
$$ LANGUAGE SQL STABLE;

-- Get time since last session
CREATE OR REPLACE FUNCTION time_since_last_session(p_profile TEXT DEFAULT 'default')
RETURNS INTERVAL AS $$
    SELECT COALESCE(
        NOW() - (
            SELECT ended_at
            FROM sessions
            WHERE profile_name = p_profile
              AND ended_at IS NOT NULL
            ORDER BY ended_at DESC
            LIMIT 1
        ),
        INTERVAL '999 days'
    );
$$ LANGUAGE SQL STABLE;

-- Archive stale thoughts (call periodically)
CREATE OR REPLACE FUNCTION archive_stale_thoughts(days_old INTEGER DEFAULT 7)
RETURNS INTEGER AS $$
DECLARE
    archived_count INTEGER;
BEGIN
    UPDATE cognition_thoughts
    SET status = 'archived',
        updated_at = NOW()
    WHERE status = 'active'
      AND created_at < NOW() - (days_old || ' days')::INTERVAL;

    GET DIAGNOSTICS archived_count = ROW_COUNT;
    RETURN archived_count;
END;
$$ LANGUAGE plpgsql;

-- migrate:down
DROP FUNCTION IF EXISTS archive_stale_thoughts;
DROP FUNCTION IF EXISTS time_since_last_session;
DROP FUNCTION IF EXISTS time_since_last_cognition;
DROP TABLE IF EXISTS cognition_cycles;
DROP TABLE IF EXISTS user_interests;
DROP TABLE IF EXISTS research_threads;
DROP TABLE IF EXISTS sessions;
DROP TABLE IF EXISTS cognition_thoughts;
