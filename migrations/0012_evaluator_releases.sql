CREATE TABLE evaluator_releases (
    id UUID PRIMARY KEY,
    workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    evaluator_key VARCHAR(64) NOT NULL,
    release_name VARCHAR(200) NOT NULL,
    version INTEGER NOT NULL CHECK (version >= 1),
    status VARCHAR(16) NOT NULL DEFAULT 'ACTIVE'
        CHECK (status IN ('ACTIVE', 'DEPRECATED')),
    metric_definitions JSONB NOT NULL DEFAULT '[]',
    thresholds JSONB NOT NULL DEFAULT '{}',
    state_version BIGINT NOT NULL DEFAULT 1 CHECK (state_version >= 1),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_evaluator_releases_key_version
        UNIQUE (workspace_id, evaluator_key, version)
);
CREATE INDEX ix_evaluator_releases_key_status
    ON evaluator_releases(workspace_id, evaluator_key, status);
