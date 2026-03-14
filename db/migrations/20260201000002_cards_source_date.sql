-- migrate:up

-- Add source_date column for original publication date (e.g., arXiv submission date)
ALTER TABLE collections.cards ADD COLUMN source_date DATE;

COMMENT ON COLUMN collections.cards.source_date IS 'Original source publication date (e.g., arXiv submission date)';

-- Update get_published_cards to return source_date
CREATE OR REPLACE FUNCTION collections.get_published_cards(max_cards INTEGER DEFAULT 50)
RETURNS TABLE (
    card_id TEXT,
    title TEXT,
    summary TEXT,
    image_url TEXT,
    source_url TEXT,
    source_type TEXT,
    published_at TIMESTAMPTZ,
    source_date DATE
) AS $$
BEGIN
    RETURN QUERY
    SELECT c.card_id, c.title, c.summary, c.image_url, c.source_url, c.source_type, c.published_at, c.source_date
    FROM collections.cards c
    JOIN collections.collections col ON c.collection_id = col.collection_id
    WHERE col.featured = TRUE
      AND c.status = 'published'
    ORDER BY c.published_at DESC
    LIMIT max_cards;
END;
$$ LANGUAGE plpgsql;

-- migrate:down
ALTER TABLE collections.cards DROP COLUMN source_date;

-- Restore original function
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
