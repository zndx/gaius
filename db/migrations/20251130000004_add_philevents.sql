-- migrate:up transaction:false

-- Add philevents source type (enum value only)
-- NOTE: ALTER TYPE ADD VALUE cannot run inside a transaction
-- NOTE: The INSERT using this value must be in a SEPARATE migration
-- because PostgreSQL doesn't allow using new enum values in the same session

ALTER TYPE source_type ADD VALUE IF NOT EXISTS 'philevents';

-- Topic reference for future migration:
-- 576 - Epistemology
-- 577 - Metaphysics
-- 578 - Philosophy of Mind
-- 574 - Philosophy of Language
-- 634 - Logic and Philosophy of Logic
-- 599 - Philosophy of Cognitive Science

-- migrate:down
-- Note: Cannot easily remove enum value in PostgreSQL
