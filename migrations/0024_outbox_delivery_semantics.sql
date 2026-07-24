-- Add durable outbox deduplication and scheduling state.

BEGIN;

ALTER TABLE outbox_events
    ADD COLUMN dedupe_key VARCHAR(255),
    ADD COLUMN status VARCHAR(32) NOT NULL DEFAULT 'PENDING',
    ADD COLUMN available_at TIMESTAMPTZ NOT NULL DEFAULT now();

UPDATE outbox_events
SET dedupe_key = event_type || ':' || aggregate_id::text || ':' || id::text
WHERE dedupe_key IS NULL;

CREATE OR REPLACE FUNCTION resolve_outbox_dedupe_key()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.dedupe_key IS NULL OR btrim(NEW.dedupe_key) = '' THEN
        NEW.dedupe_key := NEW.event_type || ':' || NEW.aggregate_id::text;
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_outbox_dedupe_key
    BEFORE INSERT ON outbox_events
    FOR EACH ROW EXECUTE FUNCTION resolve_outbox_dedupe_key();

ALTER TABLE outbox_events
    ALTER COLUMN dedupe_key SET NOT NULL;

CREATE UNIQUE INDEX uq_outbox_events_dedupe_key
    ON outbox_events(dedupe_key);

CREATE INDEX ix_outbox_dispatch
    ON outbox_events(status, available_at, created_at)
    WHERE published_at IS NULL;

COMMIT;
