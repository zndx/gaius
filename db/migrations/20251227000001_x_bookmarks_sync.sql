-- migrate:up
-- X (Twitter) Bookmarks Sync: OAuth tokens, folder mapping, sync state, rate limiting
-- Handles Free tier's 1 req/15 min rate limit with queue-based backpressure

-- ============================================================================
-- OAUTH TOKENS
-- ============================================================================

CREATE TABLE x_oauth_tokens (
    user_id VARCHAR(64) PRIMARY KEY,       -- X user ID
    username VARCHAR(64) NOT NULL,         -- @handle
    access_token TEXT NOT NULL,            -- Encrypted in app layer
    refresh_token TEXT,                    -- Encrypted in app layer
    token_type VARCHAR(32) DEFAULT 'Bearer',
    scopes TEXT[],                         -- Array of granted scopes
    expires_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

COMMENT ON TABLE x_oauth_tokens IS 'OAuth 2.0 tokens for X API access';
COMMENT ON COLUMN x_oauth_tokens.user_id IS 'X user ID (numeric string)';
COMMENT ON COLUMN x_oauth_tokens.access_token IS 'Encrypted access token';
COMMENT ON COLUMN x_oauth_tokens.refresh_token IS 'Encrypted refresh token for token renewal';

-- ============================================================================
-- OAUTH PENDING AUTH (for PKCE verifier storage)
-- ============================================================================

CREATE TABLE x_oauth_pending (
    state VARCHAR(64) PRIMARY KEY,         -- OAuth state parameter
    verifier VARCHAR(128) NOT NULL,        -- PKCE code verifier
    created_at TIMESTAMPTZ DEFAULT NOW(),
    expires_at TIMESTAMPTZ DEFAULT NOW() + INTERVAL '10 minutes'
);

CREATE INDEX idx_x_oauth_pending_expires ON x_oauth_pending(expires_at);

COMMENT ON TABLE x_oauth_pending IS 'Pending OAuth authorization flows (PKCE verifiers)';
COMMENT ON COLUMN x_oauth_pending.verifier IS 'PKCE code_verifier for token exchange';

-- Auto-cleanup expired pending auths
CREATE OR REPLACE FUNCTION x_cleanup_pending_auths()
RETURNS INTEGER AS $$
DECLARE
    v_deleted INTEGER;
BEGIN
    DELETE FROM x_oauth_pending WHERE expires_at < NOW();
    GET DIAGNOSTICS v_deleted = ROW_COUNT;
    RETURN v_deleted;
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- BOOKMARK FOLDERS
-- ============================================================================

CREATE TABLE x_bookmark_folders (
    x_folder_id VARCHAR(64) PRIMARY KEY,   -- X folder ID
    user_id VARCHAR(64) NOT NULL REFERENCES x_oauth_tokens(user_id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    kb_path VARCHAR(1024) NOT NULL,        -- e.g., current/bookmarks/papers/
    bookmark_count INTEGER DEFAULT 0,
    last_sync_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_x_folders_user ON x_bookmark_folders(user_id);

COMMENT ON TABLE x_bookmark_folders IS 'X bookmark folder to KB path mapping';
COMMENT ON COLUMN x_bookmark_folders.kb_path IS 'KB directory for this folder, e.g., current/bookmarks/papers/';

-- ============================================================================
-- BOOKMARK SYNC STATE
-- ============================================================================

CREATE TABLE x_bookmarks_sync (
    tweet_id VARCHAR(64) PRIMARY KEY,      -- X tweet ID
    folder_id VARCHAR(64) REFERENCES x_bookmark_folders(x_folder_id) ON DELETE SET NULL,
    user_id VARCHAR(64) NOT NULL REFERENCES x_oauth_tokens(user_id) ON DELETE CASCADE,
    content_hash VARCHAR(64) NOT NULL,     -- SHA-256 of tweet content
    iceberg_id UUID,                       -- Reference to HX parquet record
    kb_manifest_path VARCHAR(1024),        -- Path to manifest doc
    bookmarked_at TIMESTAMPTZ,             -- When user bookmarked it
    synced_at TIMESTAMPTZ DEFAULT NOW(),
    metadata JSONB DEFAULT '{}'
);

CREATE INDEX idx_x_bookmarks_folder ON x_bookmarks_sync(folder_id);
CREATE INDEX idx_x_bookmarks_user ON x_bookmarks_sync(user_id);
CREATE INDEX idx_x_bookmarks_synced ON x_bookmarks_sync(synced_at DESC);

COMMENT ON TABLE x_bookmarks_sync IS 'Individual bookmark sync state';
COMMENT ON COLUMN x_bookmarks_sync.content_hash IS 'SHA-256 hash for deduplication';
COMMENT ON COLUMN x_bookmarks_sync.iceberg_id IS 'Reference to raw.x_bookmarks Iceberg table';

-- ============================================================================
-- SYNC RUNS
-- ============================================================================

CREATE TABLE x_sync_runs (
    id SERIAL PRIMARY KEY,
    user_id VARCHAR(64) NOT NULL REFERENCES x_oauth_tokens(user_id) ON DELETE CASCADE,
    status VARCHAR(32) NOT NULL,           -- scheduled|running|completed|failed|rate_limited
    bookmarks_fetched INTEGER DEFAULT 0,
    bookmarks_new INTEGER DEFAULT 0,
    folders_synced INTEGER DEFAULT 0,
    pages_fetched INTEGER DEFAULT 0,       -- API pagination pages
    pagination_token VARCHAR(255),         -- Resume token for rate-limited runs
    started_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    error_message TEXT,
    metadata JSONB DEFAULT '{}'
);

CREATE INDEX idx_x_sync_runs_user ON x_sync_runs(user_id, started_at DESC);
CREATE INDEX idx_x_sync_runs_status ON x_sync_runs(status) WHERE status IN ('running', 'rate_limited');

COMMENT ON TABLE x_sync_runs IS 'Sync operation history with rate limit resume support';
COMMENT ON COLUMN x_sync_runs.pagination_token IS 'Next page token for resuming rate-limited syncs';

-- ============================================================================
-- API REQUEST QUEUE (Rate Limit Management)
-- ============================================================================

CREATE TABLE x_api_requests (
    id SERIAL PRIMARY KEY,
    user_id VARCHAR(64) NOT NULL REFERENCES x_oauth_tokens(user_id) ON DELETE CASCADE,
    request_type VARCHAR(64) NOT NULL,     -- bookmarks|bookmark_folders|users_me
    endpoint VARCHAR(255) NOT NULL,        -- Full API endpoint
    status VARCHAR(32) NOT NULL,           -- queued|executing|completed|failed|rate_limited
    priority INTEGER DEFAULT 0,            -- Higher = more urgent
    pagination_token VARCHAR(255),         -- For paginated requests
    sync_run_id INTEGER REFERENCES x_sync_runs(id) ON DELETE CASCADE,
    queued_at TIMESTAMPTZ DEFAULT NOW(),
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    response_status INTEGER,               -- HTTP status code
    rate_limit_reset_at TIMESTAMPTZ,       -- When rate limit resets
    error_message TEXT,
    metadata JSONB DEFAULT '{}'
);

CREATE INDEX idx_x_api_queued ON x_api_requests(status, priority DESC, queued_at)
    WHERE status = 'queued';
CREATE INDEX idx_x_api_user ON x_api_requests(user_id, completed_at DESC);

COMMENT ON TABLE x_api_requests IS 'Rate-limited API request queue (1 req/15 min on Free tier)';
COMMENT ON COLUMN x_api_requests.rate_limit_reset_at IS 'X-Rate-Limit-Reset header value';

-- ============================================================================
-- RATE LIMIT STATE
-- ============================================================================

CREATE TABLE x_rate_limits (
    user_id VARCHAR(64) PRIMARY KEY REFERENCES x_oauth_tokens(user_id) ON DELETE CASCADE,
    endpoint_group VARCHAR(64) NOT NULL,   -- bookmarks|users|tweets
    requests_remaining INTEGER DEFAULT 0,
    requests_limit INTEGER DEFAULT 1,      -- Free tier: 1 per 15 min
    reset_at TIMESTAMPTZ,
    last_request_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

COMMENT ON TABLE x_rate_limits IS 'Cached X API rate limit state';
COMMENT ON COLUMN x_rate_limits.endpoint_group IS 'Rate limit bucket (bookmarks share a limit)';

-- ============================================================================
-- HELPER FUNCTIONS
-- ============================================================================

-- Check if we can make an API request (rate limit check)
CREATE OR REPLACE FUNCTION x_can_request(p_user_id VARCHAR(64), p_endpoint_group VARCHAR(64) DEFAULT 'bookmarks')
RETURNS BOOLEAN AS $$
DECLARE
    v_reset_at TIMESTAMPTZ;
    v_remaining INTEGER;
BEGIN
    SELECT reset_at, requests_remaining INTO v_reset_at, v_remaining
    FROM x_rate_limits
    WHERE user_id = p_user_id AND endpoint_group = p_endpoint_group;

    -- No rate limit record = allow (first request)
    IF NOT FOUND THEN
        RETURN TRUE;
    END IF;

    -- Past reset time = allow
    IF v_reset_at IS NOT NULL AND v_reset_at <= NOW() THEN
        RETURN TRUE;
    END IF;

    -- Have remaining quota
    IF v_remaining > 0 THEN
        RETURN TRUE;
    END IF;

    RETURN FALSE;
END;
$$ LANGUAGE plpgsql;

-- Record API request and update rate limits
CREATE OR REPLACE FUNCTION x_record_request(
    p_user_id VARCHAR(64),
    p_endpoint_group VARCHAR(64),
    p_remaining INTEGER,
    p_limit INTEGER,
    p_reset_at TIMESTAMPTZ
) RETURNS VOID AS $$
BEGIN
    INSERT INTO x_rate_limits (user_id, endpoint_group, requests_remaining, requests_limit, reset_at, last_request_at, updated_at)
    VALUES (p_user_id, p_endpoint_group, p_remaining, p_limit, p_reset_at, NOW(), NOW())
    ON CONFLICT (user_id) DO UPDATE SET
        endpoint_group = EXCLUDED.endpoint_group,
        requests_remaining = EXCLUDED.requests_remaining,
        requests_limit = EXCLUDED.requests_limit,
        reset_at = EXCLUDED.reset_at,
        last_request_at = NOW(),
        updated_at = NOW();
END;
$$ LANGUAGE plpgsql;

-- Get next queued request (if rate limit allows)
CREATE OR REPLACE FUNCTION x_get_next_request(p_user_id VARCHAR(64))
RETURNS TABLE(request_id INTEGER, request_type VARCHAR(64), endpoint VARCHAR(255), pagination_token VARCHAR(255)) AS $$
BEGIN
    -- Only return if rate limit allows
    IF NOT x_can_request(p_user_id) THEN
        RETURN;
    END IF;

    RETURN QUERY
    SELECT r.id, r.request_type, r.endpoint, r.pagination_token
    FROM x_api_requests r
    WHERE r.user_id = p_user_id
      AND r.status = 'queued'
    ORDER BY r.priority DESC, r.queued_at
    LIMIT 1
    FOR UPDATE SKIP LOCKED;
END;
$$ LANGUAGE plpgsql;

-- Queue a bookmark sync request
CREATE OR REPLACE FUNCTION x_queue_bookmark_sync(
    p_user_id VARCHAR(64),
    p_sync_run_id INTEGER,
    p_pagination_token VARCHAR(255) DEFAULT NULL,
    p_priority INTEGER DEFAULT 0
) RETURNS INTEGER AS $$
DECLARE
    v_request_id INTEGER;
BEGIN
    INSERT INTO x_api_requests (user_id, request_type, endpoint, status, priority, pagination_token, sync_run_id)
    VALUES (
        p_user_id,
        'bookmarks',
        format('/2/users/%s/bookmarks', p_user_id),
        'queued',
        p_priority,
        p_pagination_token,
        p_sync_run_id
    )
    RETURNING id INTO v_request_id;

    RETURN v_request_id;
END;
$$ LANGUAGE plpgsql;

-- Start a sync run
CREATE OR REPLACE FUNCTION x_start_sync_run(p_user_id VARCHAR(64))
RETURNS INTEGER AS $$
DECLARE
    v_run_id INTEGER;
BEGIN
    INSERT INTO x_sync_runs (user_id, status)
    VALUES (p_user_id, 'running')
    RETURNING id INTO v_run_id;

    RETURN v_run_id;
END;
$$ LANGUAGE plpgsql;

-- Complete a sync run
CREATE OR REPLACE FUNCTION x_complete_sync_run(
    p_run_id INTEGER,
    p_status VARCHAR(32),
    p_bookmarks_fetched INTEGER DEFAULT 0,
    p_bookmarks_new INTEGER DEFAULT 0,
    p_folders_synced INTEGER DEFAULT 0,
    p_pagination_token VARCHAR(255) DEFAULT NULL,
    p_error_message TEXT DEFAULT NULL
) RETURNS VOID AS $$
BEGIN
    UPDATE x_sync_runs SET
        status = p_status,
        bookmarks_fetched = p_bookmarks_fetched,
        bookmarks_new = p_bookmarks_new,
        folders_synced = p_folders_synced,
        pagination_token = p_pagination_token,
        completed_at = NOW(),
        error_message = p_error_message
    WHERE id = p_run_id;
END;
$$ LANGUAGE plpgsql;

-- Check token expiry
CREATE OR REPLACE FUNCTION x_check_token_refresh(p_user_id VARCHAR(64))
RETURNS BOOLEAN AS $$
DECLARE
    v_expires_at TIMESTAMPTZ;
    v_has_refresh BOOLEAN;
BEGIN
    SELECT expires_at, refresh_token IS NOT NULL INTO v_expires_at, v_has_refresh
    FROM x_oauth_tokens
    WHERE user_id = p_user_id;

    IF NOT FOUND THEN
        RETURN FALSE;  -- No token
    END IF;

    -- Needs refresh if expires within 5 minutes
    IF v_expires_at IS NOT NULL AND v_expires_at <= NOW() + INTERVAL '5 minutes' THEN
        RETURN v_has_refresh;
    END IF;

    RETURN FALSE;  -- Token still valid
END;
$$ LANGUAGE plpgsql;

-- Get or create folder mapping
CREATE OR REPLACE FUNCTION x_upsert_folder(
    p_x_folder_id VARCHAR(64),
    p_user_id VARCHAR(64),
    p_name VARCHAR(255)
) RETURNS VARCHAR(1024) AS $$
DECLARE
    v_kb_path VARCHAR(1024);
    v_safe_name VARCHAR(255);
BEGIN
    -- Sanitize folder name for filesystem
    v_safe_name := regexp_replace(lower(p_name), '[^a-z0-9_-]', '_', 'g');
    v_kb_path := format('current/bookmarks/%s/', v_safe_name);

    INSERT INTO x_bookmark_folders (x_folder_id, user_id, name, kb_path)
    VALUES (p_x_folder_id, p_user_id, p_name, v_kb_path)
    ON CONFLICT (x_folder_id) DO UPDATE SET
        name = EXCLUDED.name,
        updated_at = NOW()
    RETURNING kb_path INTO v_kb_path;

    RETURN v_kb_path;
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- PG_CRON: Daily Bookmark Sync Trigger
-- ============================================================================

-- Function called by pg_cron to initiate daily sync
CREATE OR REPLACE FUNCTION x_trigger_daily_sync()
RETURNS TABLE(user_id VARCHAR(64), run_id INTEGER) AS $$
BEGIN
    RETURN QUERY
    SELECT t.user_id, x_start_sync_run(t.user_id)
    FROM x_oauth_tokens t
    WHERE t.refresh_token IS NOT NULL;  -- Only users with valid tokens
END;
$$ LANGUAGE plpgsql;

-- Function called by pg_cron to process request queue
-- Runs every 15 minutes to respect rate limits
CREATE OR REPLACE FUNCTION x_process_request_queue()
RETURNS INTEGER AS $$
DECLARE
    v_processed INTEGER := 0;
    v_request RECORD;
BEGIN
    -- Find users with queued requests that can proceed
    FOR v_request IN
        SELECT DISTINCT r.user_id
        FROM x_api_requests r
        WHERE r.status = 'queued'
          AND x_can_request(r.user_id)
    LOOP
        -- Mark one request per user as ready for processing
        UPDATE x_api_requests
        SET status = 'executing', started_at = NOW()
        WHERE id = (
            SELECT id FROM x_api_requests
            WHERE user_id = v_request.user_id AND status = 'queued'
            ORDER BY priority DESC, queued_at
            LIMIT 1
        );

        v_processed := v_processed + 1;
    END LOOP;

    RETURN v_processed;
END;
$$ LANGUAGE plpgsql;

-- Daily sync trigger at 6 AM
SELECT cron.schedule(
    'x-daily-bookmark-sync',
    '0 6 * * *',
    $$SELECT * FROM x_trigger_daily_sync()$$
);

-- Process request queue every 15 minutes (matches rate limit window)
SELECT cron.schedule(
    'x-process-request-queue',
    '*/15 * * * *',
    $$SELECT x_process_request_queue()$$
);

-- ============================================================================
-- MONITORING VIEW
-- ============================================================================

CREATE OR REPLACE VIEW v_x_sync_status AS
SELECT
    t.user_id,
    t.username,
    t.expires_at AS token_expires_at,
    CASE
        WHEN t.expires_at IS NULL THEN 'no_expiry'
        WHEN t.expires_at <= NOW() THEN 'expired'
        WHEN t.expires_at <= NOW() + INTERVAL '1 day' THEN 'expiring_soon'
        ELSE 'valid'
    END AS token_status,
    rl.requests_remaining,
    rl.reset_at AS rate_limit_reset,
    (SELECT COUNT(*) FROM x_bookmark_folders f WHERE f.user_id = t.user_id) AS folder_count,
    (SELECT COUNT(*) FROM x_bookmarks_sync b WHERE b.user_id = t.user_id) AS bookmark_count,
    (SELECT COUNT(*) FROM x_api_requests r WHERE r.user_id = t.user_id AND r.status = 'queued') AS queued_requests,
    (SELECT MAX(completed_at) FROM x_sync_runs r WHERE r.user_id = t.user_id AND r.status = 'completed') AS last_sync_at,
    (SELECT status FROM x_sync_runs r WHERE r.user_id = t.user_id ORDER BY started_at DESC LIMIT 1) AS last_run_status
FROM x_oauth_tokens t
LEFT JOIN x_rate_limits rl ON rl.user_id = t.user_id;

COMMENT ON VIEW v_x_sync_status IS 'X bookmark sync status per user';

-- ============================================================================
-- PERMISSIONS
-- ============================================================================

-- Grant access to gaius application user
GRANT SELECT, INSERT, UPDATE, DELETE ON x_oauth_tokens TO gaius;
GRANT SELECT, INSERT, UPDATE, DELETE ON x_oauth_pending TO gaius;
GRANT SELECT, INSERT, UPDATE, DELETE ON x_bookmark_folders TO gaius;
GRANT SELECT, INSERT, UPDATE, DELETE ON x_bookmarks_sync TO gaius;
GRANT SELECT, INSERT, UPDATE, DELETE ON x_sync_runs TO gaius;
GRANT SELECT, INSERT, UPDATE, DELETE ON x_rate_limits TO gaius;
GRANT SELECT, INSERT, UPDATE, DELETE ON x_api_requests TO gaius;
GRANT SELECT ON v_x_sync_status TO gaius;

-- Grant sequence usage for serial columns
GRANT USAGE, SELECT ON x_sync_runs_id_seq TO gaius;
GRANT USAGE, SELECT ON x_api_requests_id_seq TO gaius;

-- Grant function execute permissions
GRANT EXECUTE ON FUNCTION x_cleanup_pending_auths() TO gaius;
GRANT EXECUTE ON FUNCTION x_can_request(VARCHAR, VARCHAR) TO gaius;
GRANT EXECUTE ON FUNCTION x_record_request(VARCHAR, VARCHAR, INTEGER, INTEGER, TIMESTAMPTZ) TO gaius;
GRANT EXECUTE ON FUNCTION x_get_next_request(VARCHAR) TO gaius;
GRANT EXECUTE ON FUNCTION x_queue_bookmark_sync(VARCHAR, INTEGER, VARCHAR, INTEGER) TO gaius;
GRANT EXECUTE ON FUNCTION x_start_sync_run(VARCHAR) TO gaius;
GRANT EXECUTE ON FUNCTION x_complete_sync_run(INTEGER, VARCHAR, INTEGER, INTEGER, INTEGER, VARCHAR, TEXT) TO gaius;
GRANT EXECUTE ON FUNCTION x_check_token_refresh(VARCHAR) TO gaius;
GRANT EXECUTE ON FUNCTION x_upsert_folder(VARCHAR, VARCHAR, VARCHAR) TO gaius;
GRANT EXECUTE ON FUNCTION x_process_request_queue() TO gaius;
GRANT EXECUTE ON FUNCTION x_trigger_daily_sync() TO gaius;

-- migrate:down

-- Remove cron jobs
SELECT cron.unschedule('x-daily-bookmark-sync');
SELECT cron.unschedule('x-process-request-queue');

-- Drop view
DROP VIEW IF EXISTS v_x_sync_status;

-- Drop functions
DROP FUNCTION IF EXISTS x_trigger_daily_sync();
DROP FUNCTION IF EXISTS x_process_request_queue();
DROP FUNCTION IF EXISTS x_upsert_folder(VARCHAR, VARCHAR, VARCHAR);
DROP FUNCTION IF EXISTS x_check_token_refresh(VARCHAR);
DROP FUNCTION IF EXISTS x_complete_sync_run(INTEGER, VARCHAR, INTEGER, INTEGER, INTEGER, VARCHAR, TEXT);
DROP FUNCTION IF EXISTS x_start_sync_run(VARCHAR);
DROP FUNCTION IF EXISTS x_queue_bookmark_sync(VARCHAR, INTEGER, VARCHAR, INTEGER);
DROP FUNCTION IF EXISTS x_get_next_request(VARCHAR);
DROP FUNCTION IF EXISTS x_record_request(VARCHAR, VARCHAR, INTEGER, INTEGER, TIMESTAMPTZ);
DROP FUNCTION IF EXISTS x_can_request(VARCHAR, VARCHAR);
DROP FUNCTION IF EXISTS x_cleanup_pending_auths();

-- Drop tables (order matters for foreign keys)
DROP TABLE IF EXISTS x_api_requests;
DROP TABLE IF EXISTS x_rate_limits;
DROP TABLE IF EXISTS x_sync_runs;
DROP TABLE IF EXISTS x_bookmarks_sync;
DROP TABLE IF EXISTS x_bookmark_folders;
DROP TABLE IF EXISTS x_oauth_pending;
DROP TABLE IF EXISTS x_oauth_tokens;
