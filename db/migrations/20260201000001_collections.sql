-- migrate:up

-- ============================================================================
-- Collections Schema
-- ============================================================================
-- Curated content collections for public research materials.
-- Cards link to PUBLIC sources only (arXiv, HuggingFace, etc.) - never KB paths.
-- Articles are published externally (Substack, X), with permalinks in Gaius.
--
-- Integrates with Grok Collections API (Dec 2025) for X platform sync.

CREATE SCHEMA IF NOT EXISTS collections;
COMMENT ON SCHEMA collections IS 'Curated content collections for public landing page';

-- ============================================================================
-- Collections
-- ============================================================================

CREATE TABLE collections.collections (
    collection_id TEXT PRIMARY KEY,
    slug TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    description TEXT,

    -- Status and visibility
    status TEXT DEFAULT 'draft' CHECK (status IN ('draft', 'active', 'archived')),
    featured BOOLEAN DEFAULT FALSE,  -- Single featured collection for landing page

    -- Grok Collections API sync (Dec 2025)
    grok_collection_id TEXT,
    grok_last_sync_at TIMESTAMPTZ,

    -- Series metadata (prev:/next: linking)
    series_enabled BOOLEAN DEFAULT TRUE,

    -- KB binding
    kb_path TEXT NOT NULL,  -- e.g., 'current/collections/ai-reasoning/'

    -- Timestamps
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_collections_status ON collections.collections(status);
CREATE INDEX idx_collections_featured ON collections.collections(featured) WHERE featured = TRUE;
CREATE UNIQUE INDEX idx_collections_single_featured ON collections.collections(featured)
    WHERE featured = TRUE;  -- Ensure only one featured collection

COMMENT ON TABLE collections.collections IS 'Curated content collections for public research materials';
COMMENT ON COLUMN collections.collections.featured IS 'Only one collection can be featured at a time';
COMMENT ON COLUMN collections.collections.grok_collection_id IS 'Grok Collections API ID for X platform sync';

-- ============================================================================
-- Cards (Public-facing content items)
-- ============================================================================

CREATE TABLE collections.cards (
    card_id TEXT PRIMARY KEY,
    collection_id TEXT NOT NULL REFERENCES collections.collections(collection_id) ON DELETE CASCADE,

    -- Display fields (all public, no KB paths)
    title TEXT NOT NULL,
    summary TEXT NOT NULL,  -- 1-2 sentences for card display
    image_url TEXT,         -- OG image or screenshot
    source_url TEXT NOT NULL,  -- Link to original PUBLIC source (arXiv, HF, etc.)
    source_type TEXT NOT NULL CHECK (source_type IN (
        'arxiv', 'huggingface', 'cloudera', 'web', 'x_bookmark', 'sec_filing', 'research'
    )),

    -- Publication state
    status TEXT DEFAULT 'pending' CHECK (status IN ('pending', 'published', 'archived')),
    published_at TIMESTAMPTZ,
    sequence INTEGER,  -- Ordering within collection

    -- Series linking (for articles)
    article_id TEXT,
    prev_card_id TEXT REFERENCES collections.cards(card_id),
    next_card_id TEXT REFERENCES collections.cards(card_id),

    -- KB reference (internal, not exposed publicly)
    kb_path TEXT,

    -- Timestamps
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE(collection_id, sequence)
);

CREATE INDEX idx_cards_collection ON collections.cards(collection_id);
CREATE INDEX idx_cards_status ON collections.cards(status);
CREATE INDEX idx_cards_published ON collections.cards(published_at DESC);
CREATE INDEX idx_cards_source_type ON collections.cards(source_type);

COMMENT ON TABLE collections.cards IS 'Public-facing content cards linking to external sources';
COMMENT ON COLUMN collections.cards.source_url IS 'Link to original PUBLIC source - never internal KB paths';
COMMENT ON COLUMN collections.cards.summary IS '1-2 sentence summary for card display';

-- ============================================================================
-- Sources (Detailed provenance for cards)
-- ============================================================================

CREATE TABLE collections.sources (
    source_id TEXT PRIMARY KEY,
    card_id TEXT NOT NULL REFERENCES collections.cards(card_id) ON DELETE CASCADE,

    -- TraceableId provenance
    provenance_url TEXT NOT NULL,  -- Original source URL
    provenance_traceable_id TEXT,  -- TraceableId URI (e.g., arxiv://2312.12345)
    source_type TEXT NOT NULL,

    -- Excerpt location (precise citation)
    excerpt_text TEXT,
    excerpt_page INTEGER,
    excerpt_section TEXT,
    excerpt_char_range INT4RANGE,

    -- Ingestion metadata
    ingested_via TEXT,  -- fetch_paper, web_search, x_bookmarks_sync
    ingested_at TIMESTAMPTZ DEFAULT NOW(),

    -- KB reference (internal)
    kb_path TEXT
);

CREATE INDEX idx_sources_card ON collections.sources(card_id);

COMMENT ON TABLE collections.sources IS 'Detailed provenance for card sources with precise citations';
COMMENT ON COLUMN collections.sources.excerpt_char_range IS 'Character range [start, end) for precise excerpt location';

-- ============================================================================
-- Publications (External article links)
-- ============================================================================

CREATE TABLE collections.publications (
    publication_id TEXT PRIMARY KEY,
    collection_id TEXT NOT NULL REFERENCES collections.collections(collection_id) ON DELETE CASCADE,

    -- External platform
    platform TEXT NOT NULL CHECK (platform IN ('substack', 'x_thread', 'medium', 'custom')),
    external_url TEXT,

    -- KB article source
    article_kb_path TEXT,
    content_hash TEXT,  -- SHA-256 to detect if source changed

    -- Publication state
    status TEXT DEFAULT 'draft' CHECK (status IN ('draft', 'published')),
    published_at TIMESTAMPTZ,

    -- Timestamps
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_publications_collection ON collections.publications(collection_id);
CREATE INDEX idx_publications_platform ON collections.publications(platform);

COMMENT ON TABLE collections.publications IS 'External article publications (Substack, X threads)';
COMMENT ON COLUMN collections.publications.content_hash IS 'Detect if KB article changed since publication';

-- ============================================================================
-- Functions for /publish cards command
-- ============================================================================

-- Publish N pending cards from the featured collection
CREATE OR REPLACE FUNCTION collections.publish_cards(card_count INTEGER DEFAULT 3)
RETURNS TABLE (card_id TEXT, title TEXT, published_at TIMESTAMPTZ) AS $$
BEGIN
    RETURN QUERY
    WITH pending_cards AS (
        SELECT c.card_id, c.title
        FROM collections.cards c
        JOIN collections.collections col ON c.collection_id = col.collection_id
        WHERE col.featured = TRUE
          AND c.status = 'pending'
        ORDER BY c.sequence NULLS LAST, c.created_at ASC
        LIMIT card_count
        FOR UPDATE OF c
    ),
    updated AS (
        UPDATE collections.cards
        SET status = 'published',
            published_at = NOW(),
            updated_at = NOW()
        WHERE collections.cards.card_id IN (SELECT pc.card_id FROM pending_cards pc)
        RETURNING collections.cards.card_id, collections.cards.title, collections.cards.published_at
    )
    SELECT * FROM updated;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION collections.publish_cards IS 'Publish N pending cards from featured collection';

-- Get published cards for landing page (Cloudflare KV sync)
CREATE OR REPLACE FUNCTION collections.get_published_cards(max_cards INTEGER DEFAULT 50)
RETURNS TABLE (
    card_id TEXT,
    title TEXT,
    summary TEXT,
    image_url TEXT,
    source_url TEXT,
    source_type TEXT,
    published_at TIMESTAMPTZ
) AS $$
BEGIN
    RETURN QUERY
    SELECT c.card_id, c.title, c.summary, c.image_url, c.source_url, c.source_type, c.published_at
    FROM collections.cards c
    JOIN collections.collections col ON c.collection_id = col.collection_id
    WHERE col.featured = TRUE
      AND c.status = 'published'
    ORDER BY c.published_at DESC
    LIMIT max_cards;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION collections.get_published_cards IS 'Get published cards for landing page';

-- ============================================================================
-- Trigger for updated_at
-- ============================================================================

CREATE OR REPLACE FUNCTION collections.set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER set_collections_updated_at
    BEFORE UPDATE ON collections.collections
    FOR EACH ROW EXECUTE FUNCTION collections.set_updated_at();

CREATE TRIGGER set_cards_updated_at
    BEFORE UPDATE ON collections.cards
    FOR EACH ROW EXECUTE FUNCTION collections.set_updated_at();

CREATE TRIGGER set_publications_updated_at
    BEFORE UPDATE ON collections.publications
    FOR EACH ROW EXECUTE FUNCTION collections.set_updated_at();

-- ============================================================================
-- Base Definitions (for Bases feature store integration)
-- ============================================================================

-- Register entity type for collections
INSERT INTO bases.entity_types (entity_type_id, display_name, description, key_columns)
VALUES ('collection', 'Collection', 'Curated content collections', '[{"name": "collection_id", "type": "STRING"}]')
ON CONFLICT (entity_type_id) DO NOTHING;

-- Register collection-related bases
INSERT INTO bases.bases (base_id, display_name, description, base_type, schema, source_entity_type, physical_table, context)
VALUES
    ('collections_snapshot', 'Collections', 'Available content collections', 'snapshot',
     '[{"name": "collection_id", "type": "STRING", "nullable": false},
       {"name": "slug", "type": "STRING", "nullable": false},
       {"name": "name", "type": "STRING", "nullable": false},
       {"name": "status", "type": "STRING", "nullable": false},
       {"name": "featured", "type": "BOOLEAN", "nullable": false},
       {"name": "grok_collection_id", "type": "STRING", "nullable": true}]',
     'collection', 'collections.collections',
     '{"@vocab": "https://gaius.zndx.dev/ontology/collections/"}'),

    ('collection_cards_snapshot', 'Collection Cards', 'Public content cards', 'snapshot',
     '[{"name": "card_id", "type": "STRING", "nullable": false},
       {"name": "collection_id", "type": "STRING", "nullable": false},
       {"name": "title", "type": "STRING", "nullable": false},
       {"name": "summary", "type": "STRING", "nullable": false},
       {"name": "source_url", "type": "STRING", "nullable": false},
       {"name": "source_type", "type": "STRING", "nullable": false},
       {"name": "status", "type": "STRING", "nullable": false},
       {"name": "published_at", "type": "UNIXTIME_MICROS", "nullable": true}]',
     'collection', 'collections.cards',
     '{"@vocab": "https://gaius.zndx.dev/ontology/collections/", "source_url": {"@id": "schema:url"}, "title": {"@id": "schema:headline"}, "summary": {"@id": "schema:abstract"}}'),

    ('collection_sources_snapshot', 'Collection Sources', 'Source provenance for cards', 'snapshot',
     '[{"name": "source_id", "type": "STRING", "nullable": false},
       {"name": "card_id", "type": "STRING", "nullable": false},
       {"name": "provenance_url", "type": "STRING", "nullable": false},
       {"name": "excerpt_text", "type": "STRING", "nullable": true},
       {"name": "excerpt_page", "type": "INT32", "nullable": true},
       {"name": "ingested_via", "type": "STRING", "nullable": true}]',
     'collection', 'collections.sources',
     '{"@vocab": "https://gaius.zndx.dev/ontology/collections/", "provenance_url": {"@id": "IAO:0000219"}, "excerpt_text": {"@id": "IAO:0000300"}}')
ON CONFLICT (base_id) DO NOTHING;

-- ============================================================================
-- Grants
-- ============================================================================

GRANT USAGE ON SCHEMA collections TO gaius;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA collections TO gaius;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA collections TO gaius;

-- migrate:down
DROP SCHEMA IF EXISTS collections CASCADE;
DELETE FROM bases.bases WHERE base_id IN ('collections_snapshot', 'collection_cards_snapshot', 'collection_sources_snapshot');
DELETE FROM bases.entity_types WHERE entity_type_id = 'collection';
