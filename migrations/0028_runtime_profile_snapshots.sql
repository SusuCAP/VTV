-- Version and freeze runtime profiles, including the execution self-test gate.

BEGIN;

ALTER TABLE runtime_profiles
    DROP CONSTRAINT runtime_profiles_profile_name_key,
    ADD COLUMN profile_version INTEGER NOT NULL DEFAULT 1,
    ADD COLUMN supported_operators JSONB NOT NULL DEFAULT '[]',
    ADD COLUMN self_test_status VARCHAR(32) NOT NULL DEFAULT 'PENDING',
    ADD COLUMN numerical_regression_status VARCHAR(32) NOT NULL DEFAULT 'PENDING',
    ADD COLUMN oom_test_status VARCHAR(32) NOT NULL DEFAULT 'PENDING',
    ADD COLUMN rollback_verified BOOLEAN NOT NULL DEFAULT false,
    ADD COLUMN validation_evidence JSONB NOT NULL DEFAULT '{}',
    ADD CONSTRAINT ck_runtime_profiles_profile_version CHECK (profile_version >= 1),
    ADD CONSTRAINT ck_runtime_profiles_self_test CHECK (
        self_test_status IN ('PENDING', 'PASS', 'FAIL')
    ),
    ADD CONSTRAINT ck_runtime_profiles_numerical_regression CHECK (
        numerical_regression_status IN ('PENDING', 'PASS', 'FAIL')
    ),
    ADD CONSTRAINT ck_runtime_profiles_oom_test CHECK (
        oom_test_status IN ('PENDING', 'PASS', 'FAIL')
    ),
    ADD CONSTRAINT uq_runtime_profiles_name_version
        UNIQUE (profile_name, profile_version),
    ADD CONSTRAINT uq_runtime_profiles_image_version
        UNIQUE (image_digest, profile_version);

CREATE INDEX ix_runtime_profiles_execution_gate
    ON runtime_profiles(
        self_test_status,
        numerical_regression_status,
        oom_test_status,
        rollback_verified
    );

CREATE OR REPLACE FUNCTION reject_runtime_profile_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION
        'runtime_profiles are immutable; create a new profile version';
END;
$$;

CREATE TRIGGER trg_runtime_profiles_immutable
    BEFORE UPDATE OR DELETE ON runtime_profiles
    FOR EACH ROW EXECUTE FUNCTION reject_runtime_profile_mutation();

COMMIT;
