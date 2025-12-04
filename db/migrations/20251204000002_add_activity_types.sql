-- migrate:up

-- Add new activity types for evolution training data collection
ALTER TYPE activity_type ADD VALUE IF NOT EXISTS 'research_complete';
ALTER TYPE activity_type ADD VALUE IF NOT EXISTS 'reflection_complete';
ALTER TYPE activity_type ADD VALUE IF NOT EXISTS 'evolution_cycle';

-- migrate:down
-- Note: PostgreSQL doesn't support removing enum values
-- Would require recreating the type and migrating data
