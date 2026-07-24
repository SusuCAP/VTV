-- Complete the durable dispatch audit fields required by the stage outbox.

BEGIN;

ALTER TABLE outbox_events
    ADD COLUMN dispatched_at TIMESTAMPTZ,
    ADD COLUMN last_error JSONB;

CREATE INDEX ix_outbox_stage_dispatch_recovery
    ON outbox_events(status, updated_at)
    WHERE event_type = 'stage.dispatch.requested'
      AND published_at IS NULL;

COMMIT;
