-- migrate:up
-- Prospects/Stewardship: FMP API integration for SEC filings and institutional holdings
-- Supports daily checks ($0) and full billable analysis (Cerebras + Grok)

-- ============================================================================
-- PROSPECT CANDIDATES
-- ============================================================================

CREATE TABLE IF NOT EXISTS meta.prospect_candidates (
    id SERIAL PRIMARY KEY,
    symbol VARCHAR(16) NOT NULL,
    company_name VARCHAR(255),
    exchange VARCHAR(32),
    cik VARCHAR(32),                       -- SEC CIK number
    sector VARCHAR(64),
    industry VARCHAR(128),
    last_filing_date DATE,
    last_filing_type VARCHAR(16),          -- 10-K, 10-Q, 8-K
    pending_filings INTEGER DEFAULT 0,
    priority INTEGER DEFAULT 2,            -- 1=high, 2=medium, 3=low
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(symbol)
);

CREATE INDEX idx_prospect_candidates_symbol ON meta.prospect_candidates(symbol);
CREATE INDEX idx_prospect_candidates_priority ON meta.prospect_candidates(priority);
CREATE INDEX idx_prospect_candidates_pending ON meta.prospect_candidates(pending_filings) WHERE pending_filings > 0;

COMMENT ON TABLE meta.prospect_candidates IS 'Prospect watchlist candidates from config/prospects/watchlist.conf';
COMMENT ON COLUMN meta.prospect_candidates.cik IS 'SEC Central Index Key for EDGAR filings';
COMMENT ON COLUMN meta.prospect_candidates.pending_filings IS 'Count of new filings awaiting analysis';

-- ============================================================================
-- PROSPECT STRATEGIES
-- ============================================================================

CREATE TABLE IF NOT EXISTS meta.prospect_strategies (
    id SERIAL PRIMARY KEY,
    symbol VARCHAR(16) NOT NULL REFERENCES meta.prospect_candidates(symbol) ON DELETE CASCADE,
    profile VARCHAR(64) NOT NULL DEFAULT 'zndx',
    domain VARCHAR(64) NOT NULL DEFAULT 'prospecting',
    category VARCHAR(32) DEFAULT 'watch',  -- watch, research, position, exit
    allocation_weight REAL DEFAULT 0.0,    -- Current allocation (0-1)
    target_weight REAL DEFAULT 0.0,        -- Target allocation (0-1)
    conviction REAL DEFAULT 0.0,           -- Conviction score (0-1)
    last_analysis_at TIMESTAMPTZ,
    needs_update BOOLEAN DEFAULT FALSE,
    thesis TEXT,
    risk_notes TEXT,
    kb_artifact_path VARCHAR(512),         -- Path to latest KB artifact
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(symbol, profile, domain)
);

CREATE INDEX idx_prospect_strategies_symbol ON meta.prospect_strategies(symbol);
CREATE INDEX idx_prospect_strategies_profile ON meta.prospect_strategies(profile, domain);
CREATE INDEX idx_prospect_strategies_needs_update ON meta.prospect_strategies(needs_update) WHERE needs_update = TRUE;

COMMENT ON TABLE meta.prospect_strategies IS 'Investment strategy state per candidate per profile/domain';
COMMENT ON COLUMN meta.prospect_strategies.category IS 'Position lifecycle: watch → research → position → exit';
COMMENT ON COLUMN meta.prospect_strategies.conviction IS 'LLM-derived conviction score (0-1)';

-- ============================================================================
-- FMP SYNC RUNS
-- ============================================================================

CREATE TABLE IF NOT EXISTS meta.fmp_sync_runs (
    id SERIAL PRIMARY KEY,
    profile VARCHAR(64) NOT NULL DEFAULT 'zndx',
    domain VARCHAR(64) NOT NULL DEFAULT 'prospecting',
    run_type VARCHAR(32) NOT NULL,         -- check, update
    status VARCHAR(32) NOT NULL,           -- running, completed, failed
    symbols_processed INTEGER DEFAULT 0,
    filings_fetched INTEGER DEFAULT 0,
    filings_new INTEGER DEFAULT 0,
    holders_fetched INTEGER DEFAULT 0,
    analysis_cost_usd REAL DEFAULT 0.0,    -- Cerebras cost
    synthesis_cost_usd REAL DEFAULT 0.0,   -- Grok cost
    kb_artifacts_created INTEGER DEFAULT 0,
    started_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    error_message TEXT,
    metadata JSONB DEFAULT '{}'
);

CREATE INDEX idx_fmp_sync_runs_profile ON meta.fmp_sync_runs(profile, domain, started_at DESC);
CREATE INDEX idx_fmp_sync_runs_status ON meta.fmp_sync_runs(status) WHERE status = 'running';

COMMENT ON TABLE meta.fmp_sync_runs IS 'FMP sync operation history with cost tracking';
COMMENT ON COLUMN meta.fmp_sync_runs.analysis_cost_usd IS 'Cerebras GLM 4.7 analysis cost';
COMMENT ON COLUMN meta.fmp_sync_runs.synthesis_cost_usd IS 'XAI Grok synthesis cost';

-- ============================================================================
-- SEC FILING CACHE
-- ============================================================================

CREATE TABLE IF NOT EXISTS meta.sec_filings_cache (
    id SERIAL PRIMARY KEY,
    symbol VARCHAR(16) NOT NULL,
    filing_type VARCHAR(16) NOT NULL,      -- 10-K, 10-Q, 8-K
    filing_date DATE NOT NULL,
    accepted_date TIMESTAMPTZ,
    cik VARCHAR(32),
    accession_number VARCHAR(32),
    final_link TEXT,
    filing_hash VARCHAR(64),               -- SHA-256 for deduplication
    analyzed_at TIMESTAMPTZ,
    analysis_model VARCHAR(64),            -- Model used for analysis
    analysis_result JSONB,                 -- Structured analysis output
    iceberg_exchange_id UUID,              -- Reference to HX exchange record
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(symbol, filing_type, filing_date)
);

CREATE INDEX idx_sec_filings_symbol ON meta.sec_filings_cache(symbol, filing_date DESC);
CREATE INDEX idx_sec_filings_pending ON meta.sec_filings_cache(analyzed_at) WHERE analyzed_at IS NULL;

COMMENT ON TABLE meta.sec_filings_cache IS 'Cached SEC filings from FMP with analysis status';
COMMENT ON COLUMN meta.sec_filings_cache.iceberg_exchange_id IS 'Reference to raw.fmp_exchange Iceberg record';

-- ============================================================================
-- INSTITUTIONAL HOLDERS CACHE
-- ============================================================================

CREATE TABLE IF NOT EXISTS meta.institutional_holders_cache (
    id SERIAL PRIMARY KEY,
    symbol VARCHAR(16) NOT NULL,
    holder_name VARCHAR(255) NOT NULL,
    holder_cik VARCHAR(32),
    shares BIGINT,
    shares_change BIGINT,
    shares_change_pct REAL,
    value_usd BIGINT,
    filing_date DATE,
    fetched_at TIMESTAMPTZ DEFAULT NOW(),
    iceberg_exchange_id UUID,              -- Reference to HX exchange record
    UNIQUE(symbol, holder_name, filing_date)
);

CREATE INDEX idx_holders_symbol ON meta.institutional_holders_cache(symbol);
CREATE INDEX idx_holders_filing_date ON meta.institutional_holders_cache(filing_date DESC);

COMMENT ON TABLE meta.institutional_holders_cache IS 'Cached institutional holders from FMP 13F data';

-- ============================================================================
-- HELPER FUNCTIONS
-- ============================================================================

-- Check if a symbol has new filings since last analysis
CREATE OR REPLACE FUNCTION meta.prospect_needs_update(p_symbol VARCHAR(16))
RETURNS BOOLEAN AS $$
DECLARE
    v_last_analysis TIMESTAMPTZ;
    v_latest_filing DATE;
BEGIN
    -- Get last analysis time
    SELECT last_analysis_at INTO v_last_analysis
    FROM meta.prospect_strategies
    WHERE symbol = p_symbol
    LIMIT 1;

    -- Get latest filing date
    SELECT MAX(filing_date) INTO v_latest_filing
    FROM meta.sec_filings_cache
    WHERE symbol = p_symbol;

    -- No filings = no update needed
    IF v_latest_filing IS NULL THEN
        RETURN FALSE;
    END IF;

    -- No analysis yet = update needed
    IF v_last_analysis IS NULL THEN
        RETURN TRUE;
    END IF;

    -- New filings since last analysis = update needed
    RETURN v_latest_filing > v_last_analysis::DATE;
END;
$$ LANGUAGE plpgsql;

-- Update pending filings count for a symbol
CREATE OR REPLACE FUNCTION meta.update_pending_filings(p_symbol VARCHAR(16))
RETURNS INTEGER AS $$
DECLARE
    v_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO v_count
    FROM meta.sec_filings_cache
    WHERE symbol = p_symbol AND analyzed_at IS NULL;

    UPDATE meta.prospect_candidates
    SET pending_filings = v_count, updated_at = NOW()
    WHERE symbol = p_symbol;

    RETURN v_count;
END;
$$ LANGUAGE plpgsql;

-- Start a sync run
CREATE OR REPLACE FUNCTION meta.start_fmp_sync_run(
    p_profile VARCHAR(64),
    p_domain VARCHAR(64),
    p_run_type VARCHAR(32)
)
RETURNS INTEGER AS $$
DECLARE
    v_run_id INTEGER;
BEGIN
    INSERT INTO meta.fmp_sync_runs (profile, domain, run_type, status)
    VALUES (p_profile, p_domain, p_run_type, 'running')
    RETURNING id INTO v_run_id;

    RETURN v_run_id;
END;
$$ LANGUAGE plpgsql;

-- Complete a sync run
CREATE OR REPLACE FUNCTION meta.complete_fmp_sync_run(
    p_run_id INTEGER,
    p_status VARCHAR(32),
    p_symbols_processed INTEGER DEFAULT 0,
    p_filings_fetched INTEGER DEFAULT 0,
    p_filings_new INTEGER DEFAULT 0,
    p_analysis_cost REAL DEFAULT 0.0,
    p_synthesis_cost REAL DEFAULT 0.0,
    p_kb_artifacts INTEGER DEFAULT 0,
    p_error_message TEXT DEFAULT NULL
) RETURNS VOID AS $$
BEGIN
    UPDATE meta.fmp_sync_runs SET
        status = p_status,
        symbols_processed = p_symbols_processed,
        filings_fetched = p_filings_fetched,
        filings_new = p_filings_new,
        analysis_cost_usd = p_analysis_cost,
        synthesis_cost_usd = p_synthesis_cost,
        kb_artifacts_created = p_kb_artifacts,
        completed_at = NOW(),
        error_message = p_error_message
    WHERE id = p_run_id;
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- MONITORING VIEW
-- ============================================================================

CREATE OR REPLACE VIEW meta.v_prospects_status AS
SELECT
    c.symbol,
    c.company_name,
    c.exchange,
    c.priority,
    c.pending_filings,
    c.last_filing_date,
    c.last_filing_type,
    s.category,
    s.conviction,
    s.allocation_weight,
    s.target_weight,
    s.last_analysis_at,
    s.needs_update,
    s.profile,
    s.domain,
    (SELECT COUNT(*) FROM meta.sec_filings_cache f WHERE f.symbol = c.symbol) AS total_filings,
    (SELECT COUNT(*) FROM meta.institutional_holders_cache h WHERE h.symbol = c.symbol) AS holder_count,
    meta.prospect_needs_update(c.symbol) AS update_recommended
FROM meta.prospect_candidates c
LEFT JOIN meta.prospect_strategies s ON s.symbol = c.symbol
ORDER BY c.priority, c.symbol;

COMMENT ON VIEW meta.v_prospects_status IS 'Consolidated prospects status with update recommendations';

-- ============================================================================
-- PG_CRON: Daily FMP Check
-- ============================================================================

-- Function called by pg_cron to check for new filings
CREATE OR REPLACE FUNCTION meta.prospects_daily_check()
RETURNS TABLE(symbol VARCHAR(16), needs_update BOOLEAN, pending_filings INTEGER) AS $$
BEGIN
    RETURN QUERY
    SELECT
        c.symbol,
        meta.prospect_needs_update(c.symbol) AS needs_update,
        c.pending_filings
    FROM meta.prospect_candidates c
    WHERE c.priority <= 2;  -- Only check high/medium priority
END;
$$ LANGUAGE plpgsql;

-- Schedule daily check at 7 AM
SELECT cron.schedule(
    'prospects-daily-check',
    '0 7 * * *',
    $$SELECT * FROM meta.prospects_daily_check()$$
);

-- ============================================================================
-- PERMISSIONS
-- ============================================================================

-- Grant access to gaius application user
GRANT SELECT, INSERT, UPDATE, DELETE ON meta.prospect_candidates TO gaius;
GRANT SELECT, INSERT, UPDATE, DELETE ON meta.prospect_strategies TO gaius;
GRANT SELECT, INSERT, UPDATE, DELETE ON meta.fmp_sync_runs TO gaius;
GRANT SELECT, INSERT, UPDATE, DELETE ON meta.sec_filings_cache TO gaius;
GRANT SELECT, INSERT, UPDATE, DELETE ON meta.institutional_holders_cache TO gaius;
GRANT SELECT ON meta.v_prospects_status TO gaius;

-- Grant sequence usage
GRANT USAGE, SELECT ON meta.prospect_candidates_id_seq TO gaius;
GRANT USAGE, SELECT ON meta.prospect_strategies_id_seq TO gaius;
GRANT USAGE, SELECT ON meta.fmp_sync_runs_id_seq TO gaius;
GRANT USAGE, SELECT ON meta.sec_filings_cache_id_seq TO gaius;
GRANT USAGE, SELECT ON meta.institutional_holders_cache_id_seq TO gaius;

-- Grant function execute permissions
GRANT EXECUTE ON FUNCTION meta.prospect_needs_update(VARCHAR) TO gaius;
GRANT EXECUTE ON FUNCTION meta.update_pending_filings(VARCHAR) TO gaius;
GRANT EXECUTE ON FUNCTION meta.start_fmp_sync_run(VARCHAR, VARCHAR, VARCHAR) TO gaius;
GRANT EXECUTE ON FUNCTION meta.complete_fmp_sync_run(INTEGER, VARCHAR, INTEGER, INTEGER, INTEGER, REAL, REAL, INTEGER, TEXT) TO gaius;
GRANT EXECUTE ON FUNCTION meta.prospects_daily_check() TO gaius;

-- migrate:down

-- Remove cron job
SELECT cron.unschedule('prospects-daily-check');

-- Drop view
DROP VIEW IF EXISTS meta.v_prospects_status;

-- Drop functions
DROP FUNCTION IF EXISTS meta.prospects_daily_check();
DROP FUNCTION IF EXISTS meta.complete_fmp_sync_run(INTEGER, VARCHAR, INTEGER, INTEGER, INTEGER, REAL, REAL, INTEGER, TEXT);
DROP FUNCTION IF EXISTS meta.start_fmp_sync_run(VARCHAR, VARCHAR, VARCHAR);
DROP FUNCTION IF EXISTS meta.update_pending_filings(VARCHAR);
DROP FUNCTION IF EXISTS meta.prospect_needs_update(VARCHAR);

-- Drop tables (order matters for foreign keys)
DROP TABLE IF EXISTS meta.institutional_holders_cache;
DROP TABLE IF EXISTS meta.sec_filings_cache;
DROP TABLE IF EXISTS meta.fmp_sync_runs;
DROP TABLE IF EXISTS meta.prospect_strategies;
DROP TABLE IF EXISTS meta.prospect_candidates;
