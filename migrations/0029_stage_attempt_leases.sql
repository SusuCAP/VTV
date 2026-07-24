-- Persist attempt-level runtime identity, heartbeat, lease, and termination audit.

BEGIN;

ALTER TABLE stage_attempts
    ADD COLUMN runtime_profile_id UUID,
    ADD COLUMN gpu_type VARCHAR(64),
    ADD COLUMN lease_owner VARCHAR(200),
    ADD COLUMN lease_expires_at TIMESTAMPTZ,
    ADD COLUMN heartbeat_at TIMESTAMPTZ,
    ADD COLUMN termination_reason VARCHAR(100),
    ADD COLUMN billed_gpu_seconds NUMERIC(14, 3),
    ADD CONSTRAINT ck_stage_attempts_billed_gpu_seconds CHECK (
        billed_gpu_seconds IS NULL OR billed_gpu_seconds >= 0
    );

UPDATE stage_attempts AS attempt
SET runtime_profile_id = run.runtime_profile_uuid,
    lease_owner = run.lease_owner,
    lease_expires_at = run.lease_expires_at,
    heartbeat_at = COALESCE(attempt.started_at, attempt.created_at)
FROM stage_runs AS run
WHERE run.id = attempt.stage_run_id;

ALTER TABLE stage_attempts
    ALTER COLUMN runtime_profile_id SET NOT NULL,
    ADD CONSTRAINT fk_stage_attempts_runtime_profile
        FOREIGN KEY (runtime_profile_id)
        REFERENCES runtime_profiles(id)
        ON DELETE RESTRICT;

CREATE INDEX ix_stage_attempts_watchdog
    ON stage_attempts(status, lease_expires_at, heartbeat_at)
    WHERE finished_at IS NULL;

COMMIT;
