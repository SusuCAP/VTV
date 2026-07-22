CREATE TABLE benchmark_releases (
    id UUID PRIMARY KEY,
    workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    model_release_id UUID NOT NULL REFERENCES model_releases(id) ON DELETE CASCADE,
    dataset_key VARCHAR(128) NOT NULL,
    dataset_release VARCHAR(128) NOT NULL,
    dataset_fingerprint VARCHAR(64) NOT NULL CHECK (dataset_fingerprint ~ '^[a-f0-9]{64}$'),
    annotation_release VARCHAR(128) NOT NULL,
    policy_key VARCHAR(128) NOT NULL,
    policy_release VARCHAR(128) NOT NULL,
    policy_fingerprint VARCHAR(64) NOT NULL CHECK (policy_fingerprint ~ '^[a-f0-9]{64}$'),
    weights_sha256 VARCHAR(64) NOT NULL CHECK (weights_sha256 ~ '^[a-f0-9]{64}$'),
    runtime_fingerprint TEXT NOT NULL,
    evidence JSONB NOT NULL,
    report JSONB NOT NULL,
    approved BOOLEAN NOT NULL,
    failed_gates JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_benchmark_release_identity UNIQUE (
        model_release_id, dataset_fingerprint, policy_fingerprint, weights_sha256
    ),
    CONSTRAINT ck_benchmark_failed_gates_array CHECK (jsonb_typeof(failed_gates) = 'array'),
    CONSTRAINT ck_benchmark_approved_has_no_failures CHECK (
        approved = FALSE OR jsonb_array_length(failed_gates) = 0
    )
);

CREATE INDEX ix_benchmark_releases_workspace_model
    ON benchmark_releases(workspace_id, model_release_id);

CREATE TABLE benchmark_sample_results (
    id UUID PRIMARY KEY,
    benchmark_release_id UUID NOT NULL REFERENCES benchmark_releases(id) ON DELETE CASCADE,
    sample_id VARCHAR(128) NOT NULL,
    source_sha256 VARCHAR(64) NOT NULL CHECK (source_sha256 ~ '^[a-f0-9]{64}$'),
    critical BOOLEAN NOT NULL DEFAULT FALSE,
    result JSONB NOT NULL,
    CONSTRAINT uq_benchmark_sample_result UNIQUE (benchmark_release_id, sample_id)
);

ALTER TABLE model_releases
    ADD COLUMN approved_benchmark_release_id UUID NULL;

ALTER TABLE model_releases
    ADD CONSTRAINT fk_model_releases_approved_benchmark
    FOREIGN KEY (approved_benchmark_release_id)
    REFERENCES benchmark_releases(id)
    ON DELETE SET NULL;
