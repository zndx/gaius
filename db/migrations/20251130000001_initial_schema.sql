-- migrate:up

-- Profiles for KB customization
CREATE TABLE profiles (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    description TEXT,
    feed_config JSONB DEFAULT '{}',
    active BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_profiles_name ON profiles(name);

-- Feed source types
CREATE TYPE source_type AS ENUM (
    'arxiv',
    'biorxiv',
    'rss',
    'api',
    'scraper',
    'philpapers',
    'docs'
);

-- Feed sources configuration
CREATE TABLE feed_sources (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    source_type source_type NOT NULL,
    base_url TEXT NOT NULL,
    config JSONB DEFAULT '{}',
    -- Config examples:
    -- arxiv: {"categories": ["cs.DC"], "max_results": 50}
    -- philpapers: {"areas": ["epistemology", "philosophy-of-mind"]}
    -- docs: {"sitemap": true, "paths": ["/docs/", "/api/"]}
    fetch_interval_minutes INTEGER DEFAULT 60,
    active BOOLEAN DEFAULT true,
    last_fetch_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_feed_sources_type ON feed_sources(source_type);
CREATE INDEX idx_feed_sources_active ON feed_sources(active);

-- Profile-source associations (which profiles get which sources)
CREATE TABLE profile_sources (
    profile_id INTEGER REFERENCES profiles(id) ON DELETE CASCADE,
    source_id INTEGER REFERENCES feed_sources(id) ON DELETE CASCADE,
    weight FLOAT DEFAULT 1.0,  -- Relevance weight for this profile
    PRIMARY KEY (profile_id, source_id)
);

-- Fetched content items
CREATE TABLE content_items (
    id SERIAL PRIMARY KEY,
    source_id INTEGER REFERENCES feed_sources(id) ON DELETE SET NULL,
    external_id TEXT,  -- arxiv ID, DOI, URL hash, etc.
    url TEXT,
    title TEXT NOT NULL,
    authors TEXT[],
    summary TEXT,
    content TEXT,
    content_type TEXT DEFAULT 'text/plain',  -- text/plain, text/html, text/markdown
    metadata JSONB DEFAULT '{}',
    -- Metadata examples:
    -- arxiv: {"arxiv_id": "2311.12345", "categories": ["cs.DC"], "pdf_url": "..."}
    -- philpapers: {"area": "epistemology", "pub_date": "2024-01"}
    published_at TIMESTAMPTZ,
    fetched_at TIMESTAMPTZ DEFAULT NOW(),
    processed_at TIMESTAMPTZ,
    kb_path TEXT,  -- Path in build/dev/ if written to KB
    embedding_id TEXT,  -- Qdrant point ID if embedded
    UNIQUE(source_id, external_id)
);

CREATE INDEX idx_content_items_source ON content_items(source_id);
CREATE INDEX idx_content_items_published ON content_items(published_at DESC);
CREATE INDEX idx_content_items_fetched ON content_items(fetched_at DESC);
CREATE INDEX idx_content_items_kb_path ON content_items(kb_path) WHERE kb_path IS NOT NULL;

-- Profile-content relevance scores (computed or manual)
CREATE TABLE profile_content (
    profile_id INTEGER REFERENCES profiles(id) ON DELETE CASCADE,
    content_id INTEGER REFERENCES content_items(id) ON DELETE CASCADE,
    relevance_score FLOAT DEFAULT 0.5,
    manually_curated BOOLEAN DEFAULT false,
    added_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (profile_id, content_id)
);

CREATE INDEX idx_profile_content_score ON profile_content(profile_id, relevance_score DESC);

-- Fetch job history for debugging and monitoring
CREATE TABLE fetch_jobs (
    id SERIAL PRIMARY KEY,
    source_id INTEGER REFERENCES feed_sources(id) ON DELETE CASCADE,
    started_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    status TEXT DEFAULT 'running',  -- running, success, failed
    items_fetched INTEGER DEFAULT 0,
    items_new INTEGER DEFAULT 0,
    error_message TEXT,
    metadata JSONB DEFAULT '{}'
);

CREATE INDEX idx_fetch_jobs_source ON fetch_jobs(source_id, started_at DESC);

-- Trigger to update updated_at on profiles
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER profiles_updated_at
    BEFORE UPDATE ON profiles
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at();

-- migrate:down

DROP TRIGGER IF EXISTS profiles_updated_at ON profiles;
DROP FUNCTION IF EXISTS update_updated_at();
DROP TABLE IF EXISTS fetch_jobs;
DROP TABLE IF EXISTS profile_content;
DROP TABLE IF EXISTS content_items;
DROP TABLE IF EXISTS profile_sources;
DROP TABLE IF EXISTS feed_sources;
DROP TYPE IF EXISTS source_type;
DROP TABLE IF EXISTS profiles;
