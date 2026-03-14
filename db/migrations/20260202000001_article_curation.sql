-- migrate:up

-- ============================================================================
-- Article Curation Tables
-- ============================================================================
-- Extends collections schema with article state tracking and Atropos-RL
-- selection traces for the ArticleCurationFlow pipeline.
--
-- Articles live in KB at current/articles/{slug}/ with:
--   - article.md (current draft)
--   - zk/ (zettelkasten research notes)
--   - hx/ (draft history)
--   - sources/ (acquired external sources)
--   - manifest.yaml (collection manifest)
--   - base.md (BFO-grounded reference file)

-- ============================================================================
-- Articles (KB article state tracking)
-- ============================================================================

CREATE TABLE collections.articles (
    article_id TEXT PRIMARY KEY,
    collection_id TEXT REFERENCES collections.collections(collection_id) ON DELETE SET NULL,
    slug TEXT NOT NULL UNIQUE,

    -- Article metadata
    title TEXT NOT NULL,

    -- Status state machine: pending → researching → drafting → review → published
    status TEXT DEFAULT 'pending' CHECK (status IN (
        'pending', 'researching', 'drafting', 'review', 'published', 'abandoned'
    )),

    -- KB binding
    kb_path TEXT NOT NULL,  -- e.g., 'current/articles/ai-reasoning-weekly'

    -- Version tracking
    current_version INTEGER DEFAULT 0,

    -- Research hints (from frontmatter)
    arxiv_categories TEXT[],
    keywords TEXT[],
    news_queries TEXT[],

    -- Zettelkasten stats
    zk_count INTEGER DEFAULT 0,
    sources_count INTEGER DEFAULT 0,

    -- External publication
    external_url TEXT,  -- Substack, X thread, etc.
    external_platform TEXT CHECK (external_platform IN ('substack', 'x_thread', 'medium', 'custom')),

    -- Timestamps
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    research_started_at TIMESTAMPTZ,
    draft_completed_at TIMESTAMPTZ,
    published_at TIMESTAMPTZ
);

CREATE INDEX idx_articles_status ON collections.articles(status);
CREATE INDEX idx_articles_collection ON collections.articles(collection_id);
CREATE INDEX idx_articles_kb_path ON collections.articles(kb_path);

COMMENT ON TABLE collections.articles IS 'KB article state tracking for ArticleCurationFlow';
COMMENT ON COLUMN collections.articles.status IS 'Article lifecycle: pending → researching → drafting → review → published';
COMMENT ON COLUMN collections.articles.current_version IS 'Current draft version number (archived to hx/)';

-- ============================================================================
-- Selection Traces (Atropos-RL training data)
-- ============================================================================
-- Captures optillm article selection decisions for RL training.
-- These traces follow the Atropos RLVR format.

CREATE TABLE collections.selection_traces (
    trace_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Context
    collection_id TEXT,
    flow_run_id TEXT,

    -- Atropos-compatible fields
    item_id TEXT NOT NULL,  -- selection_<collection_id>_<timestamp>
    prompt TEXT NOT NULL,   -- Full selection prompt
    output TEXT NOT NULL,   -- JSON structured response

    -- Reward signal (computed post-hoc or inline)
    score FLOAT,
    reward_strategy TEXT,  -- binary, graded, etc.

    -- Selection specifics
    candidates JSONB NOT NULL,  -- [{card_id, title, summary, ...}]
    selected_card_id TEXT,
    selected_slug TEXT,

    -- Reasoning trace from optillm
    criteria_scores JSONB,  -- {criterion: {card_id: score}}
    tradeoffs TEXT,
    confidence FLOAT,

    -- LLM metadata
    model TEXT,
    technique TEXT,  -- cot_reflection, plansearch, bon, etc.
    temperature FLOAT,
    latency_ms INTEGER,
    tokens_used INTEGER,

    -- Timestamps
    created_at TIMESTAMPTZ DEFAULT NOW(),
    reward_computed_at TIMESTAMPTZ
);

CREATE INDEX idx_selection_traces_collection ON collections.selection_traces(collection_id);
CREATE INDEX idx_selection_traces_technique ON collections.selection_traces(technique);
CREATE INDEX idx_selection_traces_created ON collections.selection_traces(created_at DESC);
CREATE INDEX idx_selection_traces_score ON collections.selection_traces(score) WHERE score IS NOT NULL;

COMMENT ON TABLE collections.selection_traces IS 'Atropos-RL training data from article selection decisions';
COMMENT ON COLUMN collections.selection_traces.item_id IS 'Atropos-compatible item ID: selection_<collection_id>_<timestamp>';
COMMENT ON COLUMN collections.selection_traces.criteria_scores IS 'Per-criterion scores for each candidate';
COMMENT ON COLUMN collections.selection_traces.technique IS 'optillm technique used: cot_reflection, plansearch, bon, etc.';

-- ============================================================================
-- Draft History (Version tracking)
-- ============================================================================
-- Records metadata for each draft archived to hx/

CREATE TABLE collections.draft_history (
    draft_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    article_id TEXT NOT NULL REFERENCES collections.articles(article_id) ON DELETE CASCADE,

    -- Version info
    version INTEGER NOT NULL,
    filename TEXT NOT NULL,  -- e.g., 20260201T143022_draft_v001.md

    -- Content metadata
    content_hash TEXT NOT NULL,  -- SHA-256
    word_count INTEGER,
    source_count INTEGER,

    -- Generation metadata
    generator_model TEXT,
    generator_run_id TEXT,  -- Metaflow run ID
    parent_version INTEGER,

    -- Timestamps
    archived_at TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE(article_id, version)
);

CREATE INDEX idx_draft_history_article ON collections.draft_history(article_id);

COMMENT ON TABLE collections.draft_history IS 'Draft version history for articles (archived to hx/)';
COMMENT ON COLUMN collections.draft_history.filename IS 'Filename in hx/: {ISO8601}_draft_v{NNN}.md';

-- ============================================================================
-- Acquired Sources (External content for articles)
-- ============================================================================
-- Tracks sources fetched via ACP fetchers (arxiv, biorxiv, brave, etc.)

CREATE TABLE collections.acquired_sources (
    source_id TEXT PRIMARY KEY,  -- src_{type}_{hash[:12]}
    article_id TEXT NOT NULL REFERENCES collections.articles(article_id) ON DELETE CASCADE,

    -- Source info
    source_type TEXT NOT NULL CHECK (source_type IN (
        'arxiv', 'biorxiv', 'brave', 'philpapers', 'philevents', 'sec_filing', 'web'
    )),
    url TEXT NOT NULL,
    title TEXT NOT NULL,
    summary TEXT,

    -- Excerpt location (for citations)
    excerpt_text TEXT,
    excerpt_char_start INTEGER,
    excerpt_char_end INTEGER,

    -- Provenance
    traceable_id TEXT,  -- e.g., arxiv://2401.12345

    -- Metadata
    metadata JSONB,

    -- Deduplication
    content_hash TEXT,  -- SHA-256 of title+summary
    dedupe_similarity FLOAT,  -- Semantic similarity to KB content

    -- Timestamps
    fetched_at TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE(article_id, url)
);

CREATE INDEX idx_acquired_sources_article ON collections.acquired_sources(article_id);
CREATE INDEX idx_acquired_sources_type ON collections.acquired_sources(source_type);
CREATE INDEX idx_acquired_sources_url ON collections.acquired_sources(url);

COMMENT ON TABLE collections.acquired_sources IS 'External sources acquired via ACP fetchers';
COMMENT ON COLUMN collections.acquired_sources.source_id IS 'Format: src_{type}_{hash[:12]}';
COMMENT ON COLUMN collections.acquired_sources.dedupe_similarity IS 'Semantic similarity to KB (reject if > 0.92)';

-- ============================================================================
-- Article References (BFO Base file tracking)
-- ============================================================================
-- Maps references in the BFO Base file to source materials

CREATE TABLE collections.article_references (
    reference_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    article_id TEXT NOT NULL REFERENCES collections.articles(article_id) ON DELETE CASCADE,

    -- Reference info
    ref_id TEXT NOT NULL,  -- ref_001, ref_002, etc.
    source_id TEXT REFERENCES collections.acquired_sources(source_id),

    -- TraceableId provenance
    traceable_id TEXT NOT NULL,

    -- Character offsets in article body
    ref_start INTEGER NOT NULL,
    ref_end INTEGER NOT NULL,

    -- Excerpt
    excerpt TEXT NOT NULL,

    -- IAO ontology type
    iao_type TEXT DEFAULT 'IAO:0000300',  -- textual entity

    -- Timestamps
    created_at TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE(article_id, ref_id)
);

CREATE INDEX idx_article_references_article ON collections.article_references(article_id);
CREATE INDEX idx_article_references_source ON collections.article_references(source_id);

COMMENT ON TABLE collections.article_references IS 'BFO-grounded references with character offsets';
COMMENT ON COLUMN collections.article_references.ref_start IS 'Character offset start in article body';
COMMENT ON COLUMN collections.article_references.iao_type IS 'IAO ontology type (default: IAO:0000300 textual entity)';

-- ============================================================================
-- Trigger for updated_at
-- ============================================================================

CREATE TRIGGER set_articles_updated_at
    BEFORE UPDATE ON collections.articles
    FOR EACH ROW EXECUTE FUNCTION collections.set_updated_at();

-- ============================================================================
-- Views
-- ============================================================================

-- Articles ready for curation (pending with zk notes)
CREATE VIEW collections.articles_ready AS
SELECT
    a.article_id,
    a.slug,
    a.title,
    a.status,
    a.zk_count,
    a.current_version,
    a.created_at,
    c.name as collection_name
FROM collections.articles a
LEFT JOIN collections.collections c ON a.collection_id = c.collection_id
WHERE a.status IN ('pending', 'researching')
  AND a.zk_count > 0
ORDER BY a.created_at ASC;

COMMENT ON VIEW collections.articles_ready IS 'Articles ready for curation (pending/researching with zk notes)';

-- Selection trace statistics
CREATE VIEW collections.selection_trace_stats AS
SELECT
    technique,
    COUNT(*) as trace_count,
    AVG(score) as avg_score,
    AVG(confidence) as avg_confidence,
    AVG(latency_ms) as avg_latency_ms,
    AVG(tokens_used) as avg_tokens
FROM collections.selection_traces
WHERE created_at > NOW() - INTERVAL '7 days'
GROUP BY technique
ORDER BY trace_count DESC;

COMMENT ON VIEW collections.selection_trace_stats IS 'Selection trace statistics by optillm technique (last 7 days)';

-- ============================================================================
-- Bases Integration
-- ============================================================================

-- Register entity type for articles
INSERT INTO bases.entity_types (entity_type_id, display_name, description, key_columns)
VALUES ('article', 'Article', 'KB articles for curation pipeline', '[{"name": "article_id", "type": "STRING"}]')
ON CONFLICT (entity_type_id) DO NOTHING;

-- Register article-related bases (without context column which may not exist)
INSERT INTO bases.bases (base_id, display_name, description, base_type, schema, source_entity_type, physical_table)
VALUES
    ('articles_snapshot', 'Articles', 'KB articles for curation', 'snapshot',
     '[{"name": "article_id", "type": "STRING", "nullable": false},
       {"name": "slug", "type": "STRING", "nullable": false},
       {"name": "title", "type": "STRING", "nullable": false},
       {"name": "status", "type": "STRING", "nullable": false},
       {"name": "kb_path", "type": "STRING", "nullable": false},
       {"name": "current_version", "type": "INT32", "nullable": false},
       {"name": "zk_count", "type": "INT32", "nullable": false},
       {"name": "sources_count", "type": "INT32", "nullable": false}]',
     'article', 'collections.articles'),

    ('selection_traces_snapshot', 'Selection Traces', 'Atropos-RL selection training data', 'snapshot',
     '[{"name": "trace_id", "type": "STRING", "nullable": false},
       {"name": "item_id", "type": "STRING", "nullable": false},
       {"name": "selected_slug", "type": "STRING", "nullable": true},
       {"name": "technique", "type": "STRING", "nullable": true},
       {"name": "score", "type": "FLOAT", "nullable": true},
       {"name": "confidence", "type": "FLOAT", "nullable": true},
       {"name": "latency_ms", "type": "INT32", "nullable": true}]',
     'article', 'collections.selection_traces')
ON CONFLICT (base_id) DO NOTHING;

-- ============================================================================
-- Grants
-- ============================================================================

GRANT SELECT, INSERT, UPDATE, DELETE ON collections.articles TO gaius;
GRANT SELECT, INSERT, UPDATE, DELETE ON collections.selection_traces TO gaius;
GRANT SELECT, INSERT, UPDATE, DELETE ON collections.draft_history TO gaius;
GRANT SELECT, INSERT, UPDATE, DELETE ON collections.acquired_sources TO gaius;
GRANT SELECT, INSERT, UPDATE, DELETE ON collections.article_references TO gaius;
GRANT SELECT ON collections.articles_ready TO gaius;
GRANT SELECT ON collections.selection_trace_stats TO gaius;

-- migrate:down
DROP VIEW IF EXISTS collections.selection_trace_stats;
DROP VIEW IF EXISTS collections.articles_ready;
DROP TABLE IF EXISTS collections.article_references;
DROP TABLE IF EXISTS collections.acquired_sources;
DROP TABLE IF EXISTS collections.draft_history;
DROP TABLE IF EXISTS collections.selection_traces;
DROP TABLE IF EXISTS collections.articles;
DELETE FROM bases.bases WHERE base_id IN ('articles_snapshot', 'selection_traces_snapshot');
DELETE FROM bases.entity_types WHERE entity_type_id = 'article';
