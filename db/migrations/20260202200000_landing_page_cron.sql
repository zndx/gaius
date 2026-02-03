-- Landing Page Content Pipeline pg_cron Jobs
-- ============================================
-- Automated article curation and card publishing for gaius.zndx.org
--
-- Schedule (Mountain Standard Time = UTC-7):
--   article-curate: Every 36 hours (approximated via daily with cooldown check)
--   publish-cards:  4x daily for steady landing page updates (6 cards/day)
--     - 5 AM MST  (12:00 UTC) - pre-dawn, 3 cards (morning drop)
--     - 10 AM MST (17:00 UTC) - mid-morning, 1 card
--     - 2 PM MST  (21:00 UTC) - afternoon, 1 card
--     - 7 PM MST  (02:00 UTC) - early evening, 1 card

-- ============================================================================
-- Article Curation Task Handler
-- ============================================================================

-- Track last curation time for 36-hour cooldown
CREATE TABLE IF NOT EXISTS collections.curation_state (
    key TEXT PRIMARY KEY,
    last_run_at TIMESTAMPTZ,
    last_article_slug TEXT,
    run_count INTEGER DEFAULT 0
);

-- Initialize if empty
INSERT INTO collections.curation_state (key, last_run_at, run_count)
VALUES ('article_curate', NULL, 0)
ON CONFLICT (key) DO NOTHING;

-- Function to check if curation should run (36-hour cooldown)
CREATE OR REPLACE FUNCTION collections.should_run_curation()
RETURNS BOOLEAN AS $$
DECLARE
    v_last_run TIMESTAMPTZ;
    v_hours_since NUMERIC;
BEGIN
    SELECT last_run_at INTO v_last_run
    FROM collections.curation_state
    WHERE key = 'article_curate';

    IF v_last_run IS NULL THEN
        RETURN TRUE;
    END IF;

    v_hours_since := EXTRACT(EPOCH FROM (NOW() - v_last_run)) / 3600;
    RETURN v_hours_since >= 36;
END;
$$ LANGUAGE plpgsql;

-- Function to mark curation as started
CREATE OR REPLACE FUNCTION collections.mark_curation_started(p_slug TEXT DEFAULT NULL)
RETURNS VOID AS $$
BEGIN
    UPDATE collections.curation_state
    SET last_run_at = NOW(),
        last_article_slug = COALESCE(p_slug, last_article_slug),
        run_count = run_count + 1
    WHERE key = 'article_curate';
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- pg_cron Jobs
-- ============================================================================

-- Article Curation: Daily at 2 AM MST (09:00 UTC), but only runs if 36h passed
-- The scheduled_task handler checks should_run_curation() before executing
SELECT cron.schedule(
    'article-curate-daily',
    '0 9 * * *',  -- 2 AM MST = 09:00 UTC
    $$INSERT INTO scheduled_tasks (task_type, payload, source, scheduled_for)
      SELECT 'article_curate', '{"check_cooldown": true}', 'pg_cron', NOW()
      WHERE collections.should_run_curation()$$
);

-- Publish Cards: 4x daily (MST times)
-- Pre-dawn: 5 AM MST = 12:00 UTC (3 cards - bigger morning drop)
SELECT cron.schedule(
    'publish-cards-predawn',
    '0 12 * * *',
    $$INSERT INTO scheduled_tasks (task_type, payload, source, scheduled_for)
      VALUES ('publish_cards', '{"count": 3, "slot": "predawn"}', 'pg_cron', NOW())$$
);

-- Mid-morning: 10 AM MST = 17:00 UTC
SELECT cron.schedule(
    'publish-cards-morning',
    '0 17 * * *',
    $$INSERT INTO scheduled_tasks (task_type, payload, source, scheduled_for)
      VALUES ('publish_cards', '{"count": 1, "slot": "morning"}', 'pg_cron', NOW())$$
);

-- Afternoon: 2 PM MST = 21:00 UTC
SELECT cron.schedule(
    'publish-cards-afternoon',
    '0 21 * * *',
    $$INSERT INTO scheduled_tasks (task_type, payload, source, scheduled_for)
      VALUES ('publish_cards', '{"count": 1, "slot": "afternoon"}', 'pg_cron', NOW())$$
);

-- Early evening: 7 PM MST = 02:00 UTC (next day)
SELECT cron.schedule(
    'publish-cards-evening',
    '0 2 * * *',
    $$INSERT INTO scheduled_tasks (task_type, payload, source, scheduled_for)
      VALUES ('publish_cards', '{"count": 1, "slot": "evening"}', 'pg_cron', NOW())$$
);

-- ============================================================================
-- Comments
-- ============================================================================

COMMENT ON TABLE collections.curation_state IS
'Tracks article curation state for 36-hour cooldown enforcement.
Used by pg_cron job to implement non-standard cron intervals.';

COMMENT ON FUNCTION collections.should_run_curation() IS
'Returns TRUE if 36+ hours have passed since last curation run.
Called by pg_cron job to enforce cooldown period.';
