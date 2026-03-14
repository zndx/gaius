-- migrate:up

-- Add philevents source (only if not exists)
-- NOTE: This is a separate migration because PostgreSQL doesn't allow
-- using new enum values in the same session they were created

INSERT INTO feed_sources (name, source_type, base_url, config, fetch_interval_minutes, active)
SELECT
    'philevents',
    'philevents',
    'https://philevents.org',
    '{
        "topics": [577, 578, 576, 574, 634, 599],
        "max_results": 50
    }'::jsonb,
    1440,  -- Daily (events don't change that frequently)
    true
WHERE NOT EXISTS (SELECT 1 FROM feed_sources WHERE name = 'philevents');

-- Update existing philevents source to new type (if somehow exists with different type)
UPDATE feed_sources
SET source_type = 'philevents',
    config = '{
        "topics": [577, 578, 576, 574, 634, 599],
        "max_results": 50
    }'::jsonb,
    fetch_interval_minutes = 1440
WHERE name = 'philevents' AND source_type != 'philevents';

-- migrate:down

DELETE FROM feed_sources WHERE name = 'philevents';
