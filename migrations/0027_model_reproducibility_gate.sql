-- Bind model lifecycle and immutable reproducibility snapshots to execution.

BEGIN;

ALTER TABLE model_releases
    ADD COLUMN lifecycle_status VARCHAR(32) NOT NULL DEFAULT 'EXPERIMENTAL',
    ADD CONSTRAINT ck_model_releases_lifecycle_status CHECK (
        lifecycle_status IN (
            'EXPERIMENTAL',
            'CANDIDATE',
            'APPROVED_PRIMARY',
            'APPROVED_STABLE',
            'RETIRED'
        )
    );

ALTER TABLE model_access_profiles
    DROP CONSTRAINT model_access_profiles_model_release_id_key,
    DROP CONSTRAINT model_access_profiles_model_release_id_fkey,
    ADD CONSTRAINT fk_model_access_profiles_release
        FOREIGN KEY (model_release_id) REFERENCES model_releases(id) ON DELETE CASCADE,
    ADD COLUMN profile_version INTEGER NOT NULL DEFAULT 1,
    ADD COLUMN access_kind VARCHAR(32) NOT NULL DEFAULT 'UNKNOWN',
    ADD COLUMN source_url TEXT,
    ADD COLUMN code_commit VARCHAR(64),
    ADD COLUMN runtime_profile_id UUID REFERENCES runtime_profiles(id) ON DELETE RESTRICT,
    ADD COLUMN image_digest VARCHAR(128),
    ADD COLUMN launch_command TEXT,
    ADD COLUMN provider_model_id VARCHAR(256),
    ADD COLUMN provider_lifecycle VARCHAR(32),
    ADD COLUMN self_test_status VARCHAR(32) NOT NULL DEFAULT 'PENDING',
    ADD COLUMN rollback_verified BOOLEAN NOT NULL DEFAULT false,
    ADD CONSTRAINT ck_model_access_profiles_access_kind CHECK (
        access_kind IN ('UNKNOWN', 'LOCAL_WEIGHTS', 'REMOTE_API')
    ),
    ADD CONSTRAINT ck_model_access_profiles_self_test CHECK (
        self_test_status IN ('PENDING', 'PASS', 'FAIL')
    ),
    ADD CONSTRAINT uq_model_access_profiles_release_version
        UNIQUE (model_release_id, profile_version);

CREATE INDEX ix_model_access_profiles_execution_gate
    ON model_access_profiles(
        model_release_id,
        availability_status,
        self_test_status,
        rollback_verified
    );

CREATE OR REPLACE FUNCTION reject_model_access_profile_update()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION
        'model_access_profiles are immutable; create a new model release or profile version';
END;
$$;

CREATE TRIGGER trg_model_access_profiles_immutable
    BEFORE UPDATE ON model_access_profiles
    FOR EACH ROW EXECUTE FUNCTION reject_model_access_profile_update();

COMMIT;
