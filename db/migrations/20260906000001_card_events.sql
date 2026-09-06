-- migrate:up
-- 2026-09-06: the public surface's immutable history. Card status transitions
-- were not journaled anywhere: the 304 archives of 2026-09-05 and the 92 of
-- 2026-09-06 exist as hand-written TSVs under docs/notes. The composite
-- `surface_integrity` objective's CONSERVATION aspect (monotonicity: the
-- published surface never shrinks except by a declared-reason removal) reads
-- this table; an ACP remediation that archives a card is replayable and
-- auditable only because of it. Append-only by privilege.
--
-- Reason protocol: the archiver sets the reason in the same transaction —
--   SET LOCAL gaius.card_reason = 'duplicate: kept card_…';
--   SET LOCAL gaius.card_actor  = 'scripts/archive_cards.py';
-- and the trigger snapshots it. A removal without a reason is UNEXPLAINED and
-- fails the objective. Reason categories (prefix before ':'): duplicate,
-- adversarial, license, retired, broken, operator.

CREATE TABLE IF NOT EXISTS collections.card_events (
    event_id    BIGSERIAL PRIMARY KEY,
    card_id     TEXT NOT NULL,
    from_status TEXT,
    to_status   TEXT NOT NULL,
    at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    reason      TEXT,
    actor       TEXT,
    source_url  TEXT,
    title       TEXT,
    backfill    BOOLEAN NOT NULL DEFAULT FALSE
);
COMMENT ON TABLE collections.card_events IS
    'Append-only journal of card status transitions (surface_integrity conservation aspect). One row per change; reason/actor from SET LOCAL gaius.card_reason / gaius.card_actor.';
COMMENT ON COLUMN collections.card_events.reason IS
    'Why the transition happened. Required for published -> archived; empty means UNEXPLAINED. Category prefix: duplicate|adversarial|license|retired|broken|operator.';
COMMENT ON COLUMN collections.card_events.backfill IS
    'TRUE for rows reconstructed from the 2026-09-05/06 archive TSVs, before the trigger existed.';
CREATE INDEX IF NOT EXISTS idx_card_events_at ON collections.card_events (at DESC);
CREATE INDEX IF NOT EXISTS idx_card_events_card ON collections.card_events (card_id, at DESC);

CREATE OR REPLACE FUNCTION collections.record_card_event() RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        INSERT INTO collections.card_events (card_id, from_status, to_status, reason, actor, source_url, title)
        VALUES (NEW.card_id, NULL, NEW.status,
                NULLIF(current_setting('gaius.card_reason', true), ''),
                COALESCE(NULLIF(current_setting('gaius.card_actor', true), ''), current_user),
                NEW.source_url, LEFT(NEW.title, 200));
    ELSIF NEW.status IS DISTINCT FROM OLD.status THEN
        INSERT INTO collections.card_events (card_id, from_status, to_status, reason, actor, source_url, title)
        VALUES (NEW.card_id, OLD.status, NEW.status,
                NULLIF(current_setting('gaius.card_reason', true), ''),
                COALESCE(NULLIF(current_setting('gaius.card_actor', true), ''), current_user),
                NEW.source_url, LEFT(NEW.title, 200));
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS cards_status_events ON collections.cards;
CREATE TRIGGER cards_status_events
    AFTER INSERT OR UPDATE OF status ON collections.cards
    FOR EACH ROW EXECUTE FUNCTION collections.record_card_event();

GRANT SELECT, INSERT ON collections.card_events TO gaius;
GRANT USAGE, SELECT ON SEQUENCE collections.card_events_event_id_seq TO gaius;

-- migrate:down
DROP TRIGGER IF EXISTS cards_status_events ON collections.cards;
DROP FUNCTION IF EXISTS collections.record_card_event();
DROP TABLE IF EXISTS collections.card_events;
