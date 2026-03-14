-- migrate:up

-- ============================================================================
-- Article-Collection-Card Referential Integrity
-- ============================================================================
-- Enforces 1:1 article-collection mapping and strict FK on cards.
--
-- Schema invariants:
-- 1. Each article has exactly one collection (same slug)
-- 2. Each card MUST reference a valid article_id (fail-fast)
-- 3. Deleting article cascades to collection and cards
--
-- This migration must be run AFTER:
-- - 20260201000001_collections.sql (creates collections schema)
-- - 20260202000001_article_curation.sql (creates articles table)
--
-- Pre-requisites before applying NOT NULL constraint:
-- 1. Run ArticleCurationFlow to register articles in DB
-- 2. Delete orphan cards with NULL article_id
-- ============================================================================

-- ============================================================================
-- Step 1: Add FK constraint on cards.article_id
-- ============================================================================
-- Note: column already exists but has no constraint

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'cards_article_id_fkey'
        AND conrelid = 'collections.cards'::regclass
    ) THEN
        ALTER TABLE collections.cards
        ADD CONSTRAINT cards_article_id_fkey
        FOREIGN KEY (article_id)
        REFERENCES collections.articles(article_id)
        ON DELETE CASCADE;

        COMMENT ON CONSTRAINT cards_article_id_fkey ON collections.cards
            IS 'Enforces cards reference valid article (fail-fast)';
    END IF;
END $$;

-- ============================================================================
-- Step 2: Add unique constraint for 1:1 article-collection mapping
-- ============================================================================
-- Note: collection_id column already exists in articles table

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'articles_collection_id_unique'
        AND conrelid = 'collections.articles'::regclass
    ) THEN
        ALTER TABLE collections.articles
        ADD CONSTRAINT articles_collection_id_unique UNIQUE (collection_id);

        COMMENT ON CONSTRAINT articles_collection_id_unique ON collections.articles
            IS 'Enforces 1:1 article-collection mapping';
    END IF;
END $$;

-- ============================================================================
-- Step 3: Add FK from articles to collections
-- ============================================================================
-- Note: column already has REFERENCES in original migration, but let's ensure

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'articles_collection_id_fkey'
        AND conrelid = 'collections.articles'::regclass
    ) THEN
        ALTER TABLE collections.articles
        ADD CONSTRAINT articles_collection_id_fkey
        FOREIGN KEY (collection_id)
        REFERENCES collections.collections(collection_id)
        ON DELETE SET NULL;

        COMMENT ON CONSTRAINT articles_collection_id_fkey ON collections.articles
            IS 'Links article to its 1:1 collection';
    END IF;
END $$;

-- ============================================================================
-- Step 4: Create index for article_id on cards (performance)
-- ============================================================================

CREATE INDEX IF NOT EXISTS idx_cards_article_id
    ON collections.cards(article_id);

COMMENT ON INDEX collections.idx_cards_article_id
    IS 'Index for FK lookup and joins by article_id';

-- ============================================================================
-- Step 5: Enforce NOT NULL on cards.article_id
-- ============================================================================
-- NOTE: This requires all existing cards to have article_id set.
-- Run "DELETE FROM collections.cards WHERE article_id IS NULL" first if needed.

DO $$
DECLARE
    orphan_count INTEGER;
BEGIN
    -- Check for orphan cards before applying constraint
    SELECT COUNT(*) INTO orphan_count
    FROM collections.cards
    WHERE article_id IS NULL;

    IF orphan_count > 0 THEN
        RAISE EXCEPTION 'Cannot apply NOT NULL: % cards have NULL article_id. Run: DELETE FROM collections.cards WHERE article_id IS NULL', orphan_count;
    END IF;

    -- Only alter if column is currently nullable
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'collections'
        AND table_name = 'cards'
        AND column_name = 'article_id'
        AND is_nullable = 'YES'
    ) THEN
        ALTER TABLE collections.cards ALTER COLUMN article_id SET NOT NULL;
        RAISE NOTICE 'Applied NOT NULL constraint on cards.article_id';
    END IF;
END $$;

-- ============================================================================
-- Step 6: Helper function to create article with collection atomically
-- ============================================================================

CREATE OR REPLACE FUNCTION collections.create_article_with_collection(
    p_slug TEXT,
    p_title TEXT,
    p_kb_path TEXT,
    p_arxiv_categories TEXT[] DEFAULT NULL,
    p_keywords TEXT[] DEFAULT NULL
)
RETURNS TABLE (
    article_id TEXT,
    collection_id TEXT
) AS $$
DECLARE
    v_article_id TEXT;
    v_collection_id TEXT;
BEGIN
    -- Generate IDs
    v_article_id := 'art_' || replace(gen_random_uuid()::text, '-', '')::varchar(12);
    v_collection_id := 'col_' || replace(gen_random_uuid()::text, '-', '')::varchar(12);

    -- Create collection first (1:1 with article, same slug)
    INSERT INTO collections.collections (
        collection_id, slug, name, description, status, kb_path
    ) VALUES (
        v_collection_id,
        p_slug,
        p_title,
        'Cards from article: ' || p_title,
        'draft',
        'current/collections/' || p_slug || '/'
    );

    -- Create article with collection_id
    INSERT INTO collections.articles (
        article_id, slug, title, status, kb_path, collection_id,
        arxiv_categories, keywords
    ) VALUES (
        v_article_id,
        p_slug,
        p_title,
        'pending',
        p_kb_path,
        v_collection_id,
        p_arxiv_categories,
        p_keywords
    );

    RETURN QUERY SELECT v_article_id, v_collection_id;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION collections.create_article_with_collection
    IS 'Atomically create article and its 1:1 collection (same slug)';

-- ============================================================================
-- Step 6: Helper function to get article by slug
-- ============================================================================

CREATE OR REPLACE FUNCTION collections.get_article_by_slug(p_slug TEXT)
RETURNS TABLE (
    article_id TEXT,
    collection_id TEXT,
    slug TEXT,
    title TEXT,
    status TEXT,
    kb_path TEXT,
    current_version INTEGER,
    zk_count INTEGER
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        a.article_id,
        a.collection_id,
        a.slug,
        a.title,
        a.status,
        a.kb_path,
        a.current_version,
        a.zk_count
    FROM collections.articles a
    WHERE a.slug = p_slug;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION collections.get_article_by_slug
    IS 'Get article by slug for CardUpkeepFlow validation';

-- ============================================================================
-- Grants
-- ============================================================================

GRANT EXECUTE ON FUNCTION collections.create_article_with_collection TO gaius;
GRANT EXECUTE ON FUNCTION collections.get_article_by_slug TO gaius;

-- migrate:down

DROP FUNCTION IF EXISTS collections.get_article_by_slug;
DROP FUNCTION IF EXISTS collections.create_article_with_collection;
DROP INDEX IF EXISTS collections.idx_cards_article_id;

-- Remove NOT NULL constraint on article_id
ALTER TABLE collections.cards ALTER COLUMN article_id DROP NOT NULL;

ALTER TABLE collections.articles DROP CONSTRAINT IF EXISTS articles_collection_id_fkey;
ALTER TABLE collections.articles DROP CONSTRAINT IF EXISTS articles_collection_id_unique;
ALTER TABLE collections.cards DROP CONSTRAINT IF EXISTS cards_article_id_fkey;
