CREATE TABLE deliveries (
    id UUID PRIMARY KEY,
    workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    episode_id UUID NOT NULL REFERENCES episodes(id) ON DELETE CASCADE,
    version INTEGER NOT NULL CHECK (version >= 1),
    status VARCHAR(16) NOT NULL DEFAULT 'DRAFT'
        CHECK (status IN ('DRAFT', 'APPROVED', 'REVOKED')),
    state_version BIGINT NOT NULL DEFAULT 1 CHECK (state_version >= 1),
    project_state_version BIGINT NOT NULL,
    c2pa_requested BOOLEAN NOT NULL DEFAULT FALSE,
    manifest JSONB,
    manifest_fingerprint VARCHAR(64),
    approved_by VARCHAR(200),
    approved_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_deliveries_episode_version UNIQUE (episode_id, version),
    CONSTRAINT ck_deliveries_approval_payload CHECK (
        (status = 'DRAFT' AND manifest IS NULL AND manifest_fingerprint IS NULL
            AND approved_by IS NULL AND approved_at IS NULL)
        OR
        (status IN ('APPROVED', 'REVOKED') AND manifest IS NOT NULL
            AND manifest_fingerprint IS NOT NULL AND approved_by IS NOT NULL
            AND approved_at IS NOT NULL)
    )
);

CREATE INDEX ix_deliveries_project_episode_status
    ON deliveries(project_id, episode_id, status);

CREATE TABLE delivery_assets (
    delivery_id UUID NOT NULL REFERENCES deliveries(id) ON DELETE CASCADE,
    asset_id UUID NOT NULL REFERENCES media_assets(id) ON DELETE RESTRICT,
    role VARCHAR(32) NOT NULL,
    PRIMARY KEY (delivery_id, asset_id),
    CONSTRAINT uq_delivery_assets_role UNIQUE (delivery_id, role)
);
