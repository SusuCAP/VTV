-- Migration 0020: provenance_manifests, benchmark_runs, provider_usage

CREATE TABLE provenance_manifests (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id           UUID NOT NULL REFERENCES projects(id),
    delivery_id          UUID,
    episode_id           UUID,
    manifest_version     INT NOT NULL DEFAULT 1,
    source_asset_sha256  VARCHAR(64) NOT NULL,
    edit_chain           JSONB NOT NULL DEFAULT '[]',
    human_approvals      JSONB NOT NULL DEFAULT '[]',
    c2pa_embedded        BOOLEAN NOT NULL DEFAULT FALSE,
    manifest_uri         VARCHAR(2048),
    manifest_sha256      VARCHAR(64),
    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE benchmark_runs (
    id                       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    model_release_id         UUID NOT NULL REFERENCES model_releases(id),
    gpu_type                 VARCHAR(64) NOT NULL,
    runtime_profile_id       UUID NOT NULL REFERENCES runtime_profiles(id),
    dataset_version          VARCHAR(64) NOT NULL,
    total_samples            INT NOT NULL,
    passed_samples           INT NOT NULL,
    critical_failure_rate    NUMERIC(6,4) NOT NULL,
    cost_per_passed_second   NUMERIC(10,6) NOT NULL,
    p95_latency_seconds      NUMERIC(10,3) NOT NULL,
    human_reject_rate        NUMERIC(6,4) NOT NULL,
    notes                    TEXT,
    created_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (model_release_id, dataset_version)
);

CREATE TABLE provider_usage (
    id                     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id           UUID NOT NULL REFERENCES workspaces(id),
    project_id             UUID REFERENCES projects(id),
    stage_attempt_id       UUID,
    provider               VARCHAR(64) NOT NULL,
    model_id               VARCHAR(256) NOT NULL,
    request_tokens         INT NOT NULL DEFAULT 0,
    response_tokens        INT NOT NULL DEFAULT 0,
    total_cost_usd         NUMERIC(14,6) NOT NULL,
    vendor_request_id      VARCHAR(256) UNIQUE,
    data_retention_policy  VARCHAR(128) NOT NULL,
    created_at             TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
