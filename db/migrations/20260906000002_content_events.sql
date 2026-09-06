-- migrate:up
-- 2026-09-06 (user): the journal is for published CONTENT, not only cards —
-- longer-form panel-shaped content and articles (drafts in progress) will
-- transition through the same states. Rename card_events → content_events,
-- key by (content_kind, content_id), and journal collections.articles too.
-- The 2026-09-06 rows (397, incl. 396 backfilled) are kept; card_id → content_id
-- with content_kind = 'card'. Session settings generalise to
-- gaius.content_reason / gaius.content_actor (the old gaius.card_* names are
-- still read, so an in-flight archiver keeps working).

ALTER TABLE collections.card_events RENAME TO content_events;
ALTER SEQUENCE collections.card_events_event_id_seq RENAME TO content_events_event_id_seq;
ALTER TABLE collections.content_events RENAME COLUMN card_id TO content_id;
ALTER TABLE collections.content_events ADD COLUMN IF NOT EXISTS content_kind TEXT NOT NULL DEFAULT 'card';
ALTER TABLE collections.content_events
    ADD CONSTRAINT content_events_kind_check CHECK (content_kind IN ('card', 'panel', 'article'));
ALTER INDEX IF EXISTS collections.idx_card_events_at RENAME TO idx_content_events_at;
ALTER INDEX IF EXISTS collections.idx_card_events_card RENAME TO idx_content_events_content;
CREATE INDEX IF NOT EXISTS idx_content_events_kind_at ON collections.content_events (content_kind, at DESC);
COMMENT ON TABLE collections.content_events IS
    'Append-only journal of published-content status transitions (cards today; panels and articles as they publish). surface_integrity conservation aspect reads it. One row per change; reason/actor from SET LOCAL gaius.content_reason / gaius.content_actor.';
COMMENT ON COLUMN collections.content_events.content_kind IS 'card | panel | article — which table the content_id names.';
COMMENT ON COLUMN collections.content_events.reason IS
    'Why the transition happened. Required for published -> archived; empty means UNEXPLAINED. Category prefix: duplicate|adversarial|license|retired|broken|operator.';

DROP TRIGGER IF EXISTS cards_status_events ON collections.cards;
DROP FUNCTION IF EXISTS collections.record_card_event();

CREATE OR REPLACE FUNCTION collections.record_content_event() RETURNS TRIGGER AS $$
DECLARE
    v_kind   TEXT := TG_ARGV[0];
    v_id     TEXT;
    v_url    TEXT;
    v_title  TEXT;
    v_reason TEXT := COALESCE(NULLIF(current_setting('gaius.content_reason', true), ''),
                              NULLIF(current_setting('gaius.card_reason', true), ''));
    v_actor  TEXT := COALESCE(NULLIF(current_setting('gaius.content_actor', true), ''),
                              NULLIF(current_setting('gaius.card_actor', true), ''),
                              current_user);
BEGIN
    IF v_kind = 'card' THEN
        v_id := NEW.card_id; v_url := NEW.source_url; v_title := NEW.title;
    ELSIF v_kind = 'article' THEN
        v_id := NEW.article_id; v_url := NEW.external_url; v_title := NEW.title;
    ELSE
        RAISE EXCEPTION 'record_content_event: unknown content_kind %', v_kind;
    END IF;
    IF TG_OP = 'INSERT' THEN
        INSERT INTO collections.content_events (content_kind, content_id, from_status, to_status, reason, actor, source_url, title)
        VALUES (v_kind, v_id, NULL, NEW.status, v_reason, v_actor, v_url, LEFT(v_title, 200));
    ELSIF NEW.status IS DISTINCT FROM OLD.status THEN
        INSERT INTO collections.content_events (content_kind, content_id, from_status, to_status, reason, actor, source_url, title)
        VALUES (v_kind, v_id, OLD.status, NEW.status, v_reason, v_actor, v_url, LEFT(v_title, 200));
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER cards_content_events
    AFTER INSERT OR UPDATE OF status ON collections.cards
    FOR EACH ROW EXECUTE FUNCTION collections.record_content_event('card');
CREATE TRIGGER articles_content_events
    AFTER INSERT OR UPDATE OF status ON collections.articles
    FOR EACH ROW EXECUTE FUNCTION collections.record_content_event('article');

GRANT SELECT, INSERT ON collections.content_events TO gaius;
GRANT USAGE, SELECT ON SEQUENCE collections.content_events_event_id_seq TO gaius;

-- migrate:down
DROP TRIGGER IF EXISTS articles_content_events ON collections.articles;
DROP TRIGGER IF EXISTS cards_content_events ON collections.cards;
DROP FUNCTION IF EXISTS collections.record_content_event();
ALTER TABLE collections.content_events DROP CONSTRAINT IF EXISTS content_events_kind_check;
ALTER TABLE collections.content_events DROP COLUMN IF EXISTS content_kind;
ALTER TABLE collections.content_events RENAME COLUMN content_id TO card_id;
ALTER SEQUENCE collections.content_events_event_id_seq RENAME TO card_events_event_id_seq;
ALTER TABLE collections.content_events RENAME TO card_events;
