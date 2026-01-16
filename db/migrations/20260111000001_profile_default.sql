-- migrate:up

-- ============================================================================
-- PROFILE DEFAULT FLAG
-- Add is_default column with partial unique index to enforce single default
-- ============================================================================

-- Add is_default column to profiles
ALTER TABLE profiles ADD COLUMN IF NOT EXISTS is_default BOOLEAN DEFAULT FALSE;

COMMENT ON COLUMN profiles.is_default IS
    'Only one profile can be the default. Used when no profile is specified on CLI.';

-- Partial unique index ensures only one profile can have is_default = TRUE
-- This is the PostgreSQL idiom for "at most one TRUE" constraint
CREATE UNIQUE INDEX IF NOT EXISTS idx_profiles_default
    ON profiles ((1)) WHERE is_default = TRUE;

-- Set 'common' as the default profile (shared temporal grounding)
-- If 'common' doesn't exist, this is a no-op
UPDATE profiles SET is_default = TRUE WHERE name = 'common';

-- ============================================================================
-- HELPER FUNCTIONS
-- ============================================================================

-- Get the default profile name
CREATE OR REPLACE FUNCTION get_default_profile()
RETURNS TEXT AS $$
DECLARE
    v_profile_name TEXT;
BEGIN
    -- Get the profile marked as default
    SELECT name INTO v_profile_name
    FROM profiles
    WHERE is_default = TRUE AND active = TRUE;

    -- Fall back to first active profile if no default set
    IF v_profile_name IS NULL THEN
        SELECT name INTO v_profile_name
        FROM profiles
        WHERE active = TRUE
        ORDER BY name
        LIMIT 1;
    END IF;

    RETURN v_profile_name;
END;
$$ LANGUAGE plpgsql;

-- Set a profile as the default (atomically clears previous default)
CREATE OR REPLACE FUNCTION set_default_profile(p_profile_name TEXT)
RETURNS BOOLEAN AS $$
BEGIN
    -- Clear any existing default
    UPDATE profiles SET is_default = FALSE WHERE is_default = TRUE;

    -- Set the new default
    UPDATE profiles SET is_default = TRUE WHERE name = p_profile_name AND active = TRUE;

    -- Return whether the update succeeded
    RETURN FOUND;
END;
$$ LANGUAGE plpgsql;

-- Get default profile and its active domain (for CLI resolution)
CREATE OR REPLACE FUNCTION get_default_profile_and_domain()
RETURNS TABLE(profile_name TEXT, domain_name TEXT) AS $$
DECLARE
    v_profile TEXT;
    v_domain TEXT;
BEGIN
    -- Get default profile
    v_profile := get_default_profile();

    IF v_profile IS NOT NULL THEN
        -- Get active domain for that profile
        v_domain := get_active_domain(v_profile);
    END IF;

    RETURN QUERY SELECT v_profile, v_domain;
END;
$$ LANGUAGE plpgsql;

-- migrate:down

DROP FUNCTION IF EXISTS get_default_profile_and_domain();
DROP FUNCTION IF EXISTS set_default_profile(TEXT);
DROP FUNCTION IF EXISTS get_default_profile();

DROP INDEX IF EXISTS idx_profiles_default;

ALTER TABLE profiles DROP COLUMN IF EXISTS is_default;
