-- Migration 0015: locations and location_releases
-- Persists recurring scene clustering and localization asset versions.

BEGIN;

CREATE TABLE locations (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id      UUID        NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    display_name    VARCHAR(200) NOT NULL,
    localized_name  VARCHAR(200),
    -- INTERIOR / EXTERIOR / VEHICLE / OTHER
    location_type   VARCHAR(32),
    cluster_fingerprint VARCHAR(64),
    confirmed       BOOLEAN     NOT NULL DEFAULT FALSE,
    notes           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX ix_locations_project ON locations(project_id);

CREATE TABLE location_releases (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id      UUID        NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    location_id     UUID        NOT NULL REFERENCES locations(id) ON DELETE CASCADE,
    version         INTEGER     NOT NULL DEFAULT 1,
    status          VARCHAR(32) NOT NULL DEFAULT 'DRAFT',
    -- S3 URI to location anchor pack (establishing shot, key surfaces, lighting)
    anchor_pack_uri VARCHAR(2048),
    anchor_pack_sha256 VARCHAR(64),
    model_release_ids JSONB     NOT NULL DEFAULT '[]',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_location_releases_version UNIQUE (location_id, version),
    CONSTRAINT ck_location_releases_version CHECK (version >= 1),
    CONSTRAINT ck_location_releases_status
        CHECK (status IN ('DRAFT', 'CONFIRMED', 'RELEASED', 'SUPERSEDED'))
);

CREATE INDEX ix_location_releases_project ON location_releases(project_id, status);

COMMIT;
