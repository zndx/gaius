-- migrate:up

-- ============================================================================
-- PROFILE EXTENSIONS
-- Add unstructured text fields and KB path configuration to profiles
-- ============================================================================

-- Add profile_text for agentic use (prompting context)
ALTER TABLE profiles ADD COLUMN IF NOT EXISTS profile_text TEXT;

-- KB path prefixes for this profile (e.g., ['current/cloudera/'])
ALTER TABLE profiles ADD COLUMN IF NOT EXISTS kb_path_prefixes TEXT[] DEFAULT '{}';

-- Search boost multiplier (deferred feature, but schema-ready)
ALTER TABLE profiles ADD COLUMN IF NOT EXISTS search_boost FLOAT DEFAULT 1.0;

COMMENT ON COLUMN profiles.profile_text IS
    'Unstructured text for agent prompting context. Describes profile purpose, conventions, priorities.';
COMMENT ON COLUMN profiles.kb_path_prefixes IS
    'KB path prefixes associated with this profile. Used for search boosting and organization.';
COMMENT ON COLUMN profiles.search_boost IS
    'Default search result boost multiplier for content matching profile paths (1.0 = neutral).';

-- ============================================================================
-- PROFILE DOMAINS
-- Domains are profile-scoped focus areas (e.g., 'csa' within 'cloudera')
-- ============================================================================

CREATE TABLE profile_domains (
    id SERIAL PRIMARY KEY,
    profile_id INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    name TEXT NOT NULL,                     -- e.g., 'csa' (lowercase)
    display_name TEXT,                      -- e.g., 'CSA Operator'
    description TEXT,

    -- Agentic text field for agent prompting
    domain_text TEXT,

    -- KB path mapping for this domain
    kb_path_prefixes TEXT[] DEFAULT '{}',   -- e.g., ['current/cloudera/docs/csa/']
    search_boost FLOAT DEFAULT 1.0,         -- Multiplier for search results

    -- Domain state
    is_active BOOLEAN DEFAULT FALSE,        -- Only one active per profile at a time

    -- Timestamps
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE(profile_id, name)
);

CREATE INDEX idx_profile_domains_profile ON profile_domains(profile_id);
CREATE INDEX idx_profile_domains_active ON profile_domains(profile_id) WHERE is_active;

COMMENT ON TABLE profile_domains IS
    'Domains are profile-scoped focus areas. The same domain name can exist in multiple profiles.';
COMMENT ON COLUMN profile_domains.domain_text IS
    'Unstructured text for agent prompting. Describes domain concepts, terminology, and goals.';
COMMENT ON COLUMN profile_domains.is_active IS
    'Only one domain can be active per profile at a time. Used for context switching.';

-- ============================================================================
-- HELPER FUNCTIONS
-- ============================================================================

-- Atomically set the active domain for a profile
-- Creates the domain if it doesn't exist
CREATE OR REPLACE FUNCTION set_active_domain(
    p_profile_name TEXT,
    p_domain_name TEXT
) RETURNS BOOLEAN AS $$
DECLARE
    v_profile_id INTEGER;
BEGIN
    -- Get profile ID
    SELECT id INTO v_profile_id
    FROM profiles
    WHERE name = p_profile_name;

    IF v_profile_id IS NULL THEN
        RAISE EXCEPTION 'Profile "%" not found', p_profile_name;
    END IF;

    -- Deactivate all domains for this profile
    UPDATE profile_domains
    SET is_active = FALSE, updated_at = NOW()
    WHERE profile_id = v_profile_id AND is_active = TRUE;

    -- Handle 'open' or NULL as clearing the domain
    IF p_domain_name IS NULL OR p_domain_name = '' OR p_domain_name = 'open' THEN
        RETURN TRUE;
    END IF;

    -- Activate the specified domain (upsert)
    INSERT INTO profile_domains (profile_id, name, is_active)
    VALUES (v_profile_id, p_domain_name, TRUE)
    ON CONFLICT (profile_id, name)
    DO UPDATE SET is_active = TRUE, updated_at = NOW();

    RETURN TRUE;
END;
$$ LANGUAGE plpgsql;

-- Get the currently active domain for a profile
CREATE OR REPLACE FUNCTION get_active_domain(
    p_profile_name TEXT
) RETURNS TEXT AS $$
DECLARE
    v_domain_name TEXT;
BEGIN
    SELECT pd.name INTO v_domain_name
    FROM profile_domains pd
    JOIN profiles p ON pd.profile_id = p.id
    WHERE p.name = p_profile_name AND pd.is_active = TRUE;

    RETURN v_domain_name;
END;
$$ LANGUAGE plpgsql;

-- Get combined profile + domain context for agent prompting
CREATE OR REPLACE FUNCTION get_profile_context(
    p_profile_name TEXT,
    p_domain_name TEXT DEFAULT NULL
) RETURNS JSONB AS $$
DECLARE
    v_result JSONB;
    v_profile_text TEXT;
    v_domain_text TEXT;
    v_profile_prefixes TEXT[];
    v_domain_prefixes TEXT[];
BEGIN
    -- Get profile info
    SELECT profile_text, kb_path_prefixes
    INTO v_profile_text, v_profile_prefixes
    FROM profiles
    WHERE name = p_profile_name;

    IF NOT FOUND THEN
        RETURN jsonb_build_object('error', 'Profile not found');
    END IF;

    v_result := jsonb_build_object(
        'profile', p_profile_name,
        'profile_text', COALESCE(v_profile_text, ''),
        'profile_prefixes', COALESCE(v_profile_prefixes, '{}')
    );

    -- Get domain info if specified
    IF p_domain_name IS NOT NULL AND p_domain_name != '' AND p_domain_name != 'open' THEN
        SELECT domain_text, kb_path_prefixes
        INTO v_domain_text, v_domain_prefixes
        FROM profile_domains pd
        JOIN profiles p ON pd.profile_id = p.id
        WHERE p.name = p_profile_name AND pd.name = p_domain_name;

        IF FOUND THEN
            v_result := v_result || jsonb_build_object(
                'domain', p_domain_name,
                'domain_text', COALESCE(v_domain_text, ''),
                'domain_prefixes', COALESCE(v_domain_prefixes, '{}')
            );
        END IF;
    END IF;

    RETURN v_result;
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- DOC ARCHIVES
-- Track documentation archives for ETL processing
-- ============================================================================

CREATE TABLE doc_archives (
    id SERIAL PRIMARY KEY,
    source_id INTEGER NOT NULL REFERENCES feed_sources(id) ON DELETE CASCADE,

    -- Archive identification
    archive_url TEXT NOT NULL,              -- URL of the docs archive (ZIP, HTML, etc.)
    version TEXT,                           -- Version string if known
    content_hash TEXT,                      -- SHA-256 for change detection

    -- Processing status
    status TEXT DEFAULT 'discovered',       -- discovered, downloading, extracting, completed, failed
    kb_path_prefix TEXT,                    -- e.g., 'current/cloudera/docs/csa/'
    pages_extracted INTEGER DEFAULT 0,

    -- Error tracking
    error_message TEXT,
    retry_count INTEGER DEFAULT 0,

    -- Timestamps
    discovered_at TIMESTAMPTZ DEFAULT NOW(),
    processed_at TIMESTAMPTZ,

    UNIQUE(source_id, archive_url)
);

CREATE INDEX idx_doc_archives_source ON doc_archives(source_id);
CREATE INDEX idx_doc_archives_status ON doc_archives(status);

COMMENT ON TABLE doc_archives IS
    'Tracks documentation archives discovered for ETL processing.';
COMMENT ON COLUMN doc_archives.content_hash IS
    'SHA-256 hash of archive content for incremental sync (skip if unchanged).';

-- ============================================================================
-- ARCHIVE ROTATIONS
-- Track quarterly archive rotations for docs
-- ============================================================================

CREATE TABLE archive_rotations (
    id SERIAL PRIMARY KEY,
    quarter TEXT NOT NULL,                  -- e.g., '2025Q1'
    doc_archive_id INTEGER REFERENCES doc_archives(id) ON DELETE SET NULL,

    -- Paths
    source_kb_path TEXT NOT NULL,           -- current/cloudera/docs/csa/
    archive_kb_path TEXT NOT NULL,          -- archive/2025Q1/cloudera/docs/csa/
    version_at_archive TEXT,                -- Version when archived

    -- Status
    status TEXT DEFAULT 'pending',          -- pending, in_progress, completed, skipped
    files_moved INTEGER DEFAULT 0,

    created_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ
);

CREATE INDEX idx_archive_rotations_quarter ON archive_rotations(quarter);
CREATE INDEX idx_archive_rotations_status ON archive_rotations(status);

COMMENT ON TABLE archive_rotations IS
    'Tracks quarterly archive rotations. Docs are moved to archive/ on version change.';

-- ============================================================================
-- UI PREFERENCES EXTENSION
-- Track active profile for session persistence
-- ============================================================================

ALTER TABLE ui_preferences
    ADD COLUMN IF NOT EXISTS profile_name TEXT DEFAULT 'default',
    ADD COLUMN IF NOT EXISTS profile_changed_at TIMESTAMPTZ;

COMMENT ON COLUMN ui_preferences.profile_name IS
    'Currently active profile name for this UI session.';

-- migrate:down

DROP FUNCTION IF EXISTS get_profile_context(TEXT, TEXT);
DROP FUNCTION IF EXISTS get_active_domain(TEXT);
DROP FUNCTION IF EXISTS set_active_domain(TEXT, TEXT);

DROP TABLE IF EXISTS archive_rotations;
DROP TABLE IF EXISTS doc_archives;
DROP TABLE IF EXISTS profile_domains;

ALTER TABLE ui_preferences DROP COLUMN IF EXISTS profile_changed_at;
ALTER TABLE ui_preferences DROP COLUMN IF EXISTS profile_name;

ALTER TABLE profiles DROP COLUMN IF EXISTS search_boost;
ALTER TABLE profiles DROP COLUMN IF EXISTS kb_path_prefixes;
ALTER TABLE profiles DROP COLUMN IF EXISTS profile_text;
