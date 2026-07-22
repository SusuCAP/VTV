CREATE TABLE rights_releases (
    id UUID PRIMARY KEY,
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    subject_type VARCHAR(32) NOT NULL,
    subject_id VARCHAR(128) NOT NULL,
    version INTEGER NOT NULL CHECK (version >= 1),
    status VARCHAR(16) NOT NULL DEFAULT 'ACTIVE'
        CHECK (status IN ('ACTIVE', 'REVOKED')),
    state_version BIGINT NOT NULL DEFAULT 1 CHECK (state_version >= 1),
    allowed_operations JSONB NOT NULL CHECK (jsonb_typeof(allowed_operations) = 'array'),
    allowed_markets JSONB NOT NULL CHECK (jsonb_typeof(allowed_markets) = 'array'),
    allowed_languages JSONB NOT NULL CHECK (jsonb_typeof(allowed_languages) = 'array'),
    commercial_scope VARCHAR(32) NOT NULL
        CHECK (commercial_scope IN ('RESEARCH_ONLY', 'COMMERCIAL')),
    valid_from TIMESTAMPTZ NOT NULL,
    expires_at TIMESTAMPTZ NULL,
    revoked_at TIMESTAMPTZ NULL,
    revoked_by UUID NULL,
    revocation_reason TEXT NULL,
    minor_guardian_consent BOOLEAN NOT NULL DEFAULT FALSE,
    source_asset_ids JSONB NOT NULL DEFAULT '[]'::jsonb
        CHECK (jsonb_typeof(source_asset_ids) = 'array'),
    evidence_uri TEXT NOT NULL,
    evidence_sha256 VARCHAR(64) NOT NULL CHECK (evidence_sha256 ~ '^[a-f0-9]{64}$'),
    supersedes_release_id UUID NULL REFERENCES rights_releases(id) ON DELETE SET NULL,
    created_by UUID NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_rights_release_version
        UNIQUE (project_id, subject_type, subject_id, version),
    CONSTRAINT ck_rights_release_window
        CHECK (expires_at IS NULL OR expires_at > valid_from)
);

CREATE UNIQUE INDEX uq_rights_releases_current_subject
    ON rights_releases(project_id, subject_type, subject_id)
    WHERE revoked_at IS NULL;

CREATE INDEX ix_rights_releases_project_status
    ON rights_releases(project_id, status);
