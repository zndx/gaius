-- migrate:up
-- Add soft archive support for prospect_candidates
-- Config file is the driver; removed symbols are archived, not deleted

-- Add active flag and archive timestamp
ALTER TABLE meta.prospect_candidates
    ADD COLUMN IF NOT EXISTS active BOOLEAN DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS archived_at TIMESTAMPTZ;

-- Index for efficient active-only queries
CREATE INDEX IF NOT EXISTS idx_prospect_candidates_active
    ON meta.prospect_candidates(active) WHERE active = TRUE;

-- Update comments
COMMENT ON COLUMN meta.prospect_candidates.active IS 'Whether symbol is in active watchlist config';
COMMENT ON COLUMN meta.prospect_candidates.archived_at IS 'When symbol was removed from config (soft archive)';

-- Function to sync watchlist config to database
-- Activates symbols in config, archives those not in config
CREATE OR REPLACE FUNCTION meta.sync_prospect_watchlist(
    p_symbols VARCHAR(16)[],
    p_profile VARCHAR(64) DEFAULT 'zndx'
)
RETURNS TABLE(
    activated INTEGER,
    archived INTEGER,
    unchanged INTEGER
) AS $$
DECLARE
    v_activated INTEGER := 0;
    v_archived INTEGER := 0;
    v_unchanged INTEGER := 0;
BEGIN
    -- Activate symbols that are in config but inactive
    UPDATE meta.prospect_candidates
    SET active = TRUE, archived_at = NULL, updated_at = NOW()
    WHERE symbol = ANY(p_symbols) AND active = FALSE;
    GET DIAGNOSTICS v_activated = ROW_COUNT;

    -- Archive symbols that are active but not in config
    UPDATE meta.prospect_candidates
    SET active = FALSE, archived_at = NOW(), updated_at = NOW()
    WHERE symbol NOT IN (SELECT unnest(p_symbols)) AND active = TRUE;
    GET DIAGNOSTICS v_archived = ROW_COUNT;

    -- Count unchanged
    SELECT COUNT(*) INTO v_unchanged
    FROM meta.prospect_candidates
    WHERE symbol = ANY(p_symbols) AND active = TRUE;
    v_unchanged := v_unchanged - v_activated;

    RETURN QUERY SELECT v_activated, v_archived, v_unchanged;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION meta.sync_prospect_watchlist(VARCHAR[], VARCHAR) IS
    'Sync watchlist config to DB: activate configured symbols, archive removed ones';

-- Update the status view to filter by active
DROP VIEW IF EXISTS meta.v_prospects_status;
CREATE OR REPLACE VIEW meta.v_prospects_status AS
SELECT
    c.symbol,
    c.company_name,
    c.exchange,
    c.priority,
    c.pending_filings,
    c.last_filing_date,
    c.last_filing_type,
    c.active,
    c.archived_at,
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
WHERE c.active = TRUE  -- Only show active candidates
ORDER BY c.priority, c.symbol;

COMMENT ON VIEW meta.v_prospects_status IS 'Consolidated prospects status for active candidates only';

-- Grant execute on new function
GRANT EXECUTE ON FUNCTION meta.sync_prospect_watchlist(VARCHAR[], VARCHAR) TO gaius;

-- migrate:down

-- Restore original view (without active filter)
DROP VIEW IF EXISTS meta.v_prospects_status;
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

-- Drop function
DROP FUNCTION IF EXISTS meta.sync_prospect_watchlist(VARCHAR[], VARCHAR);

-- Drop index
DROP INDEX IF EXISTS meta.idx_prospect_candidates_active;

-- Remove columns
ALTER TABLE meta.prospect_candidates
    DROP COLUMN IF EXISTS archived_at,
    DROP COLUMN IF EXISTS active;
