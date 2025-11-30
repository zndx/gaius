-- Add philevents source type and source entry
-- Run as: psql -f db/migrations/20251130000004_add_philevents.sql

-- Add philevents to source_type enum
ALTER TYPE source_type ADD VALUE IF NOT EXISTS 'philevents';

-- Add philevents source (only if not exists)
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

-- Update existing philevents source to new type
UPDATE feed_sources
SET source_type = 'philevents',
    config = '{
        "topics": [577, 578, 576, 574, 634, 599],
        "max_results": 50
    }'::jsonb,
    fetch_interval_minutes = 1440
WHERE name = 'philevents' AND source_type != 'philevents';

-- Topic reference:
-- 576 - Epistemology
-- 577 - Metaphysics
-- 578 - Philosophy of Mind
-- 574 - Philosophy of Language
-- 634 - Logic and Philosophy of Logic
-- 599 - Philosophy of Cognitive Science
