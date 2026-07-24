-- Migration 0016: continuity_snapshots and anchor_assets
-- Per-shot continuity state and multi-type anchor asset registry.

BEGIN;

-- anchor_assets: named reference assets for Character/Look/Location/Voice/Neighbor
CREATE TABLE anchor_assets (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id      UUID        NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    -- CHARACTER | LOOK | LOCATION | VOICE | NEIGHBOR
    anchor_type     VARCHAR(32) NOT NULL,
    -- FK to the owning release (character_releases / location_releases / etc.)
    owner_type      VARCHAR(64) NOT NULL,
    owner_id        UUID        NOT NULL,
    label           VARCHAR(200) NOT NULL,
    -- S3 URI + hash
    asset_uri       VARCHAR(2048) NOT NULL,
    asset_sha256    VARCHAR(64)  NOT NULL,
    media_type      VARCHAR(128) NOT NULL,
    -- Structured metadata: pose, expression, lighting, etc.
    metadata        JSONB       NOT NULL DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_anchor_assets_type
        CHECK (anchor_type IN ('CHARACTER', 'LOOK', 'LOCATION', 'VOICE', 'NEIGHBOR'))
);

CREATE INDEX ix_anchor_assets_project  ON anchor_assets(project_id);
CREATE INDEX ix_anchor_assets_owner    ON anchor_assets(owner_type, owner_id);

-- continuity_snapshots: immutable per-shot continuity state snapshot
-- Created by the orchestrator before each visual production stage to freeze
-- the active character/look/location/geometry state at that shot boundary.
CREATE TABLE continuity_snapshots (
    id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id          UUID        NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    episode_id          UUID        NOT NULL REFERENCES episodes(id) ON DELETE CASCADE,
    shot_id             UUID        NOT NULL,
    snapshot_version    INTEGER     NOT NULL DEFAULT 1,
    -- Active releases frozen at this snapshot
    character_releases  JSONB       NOT NULL DEFAULT '[]',  -- [{character_id, release_id}]
    look_states         JSONB       NOT NULL DEFAULT '[]',  -- [{character_id, look_state_id}]
    location_release_id UUID        REFERENCES location_releases(id),
    -- Geometry: screen direction, camera pose asset URI, depth asset URI
    geometry_payload    JSONB       NOT NULL DEFAULT '',
    -- Neighbor frames: prev tail, next head, nearest QC-passed frame URIs
    neighbor_frames     JSONB       NOT NULL DEFAULT '{}',
    localization_release_id UUID,
    -- SHA-256 of the entire snapshot payload (deterministic fingerprint)
    continuity_fingerprint VARCHAR(64) NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_continuity_snapshots_shot_version
        UNIQUE (shot_id, snapshot_version),
    CONSTRAINT ck_continuity_snapshots_version
        CHECK (snapshot_version >= 1)
);

CREATE INDEX ix_continuity_snapshots_project ON continuity_snapshots(project_id);
CREATE INDEX ix_continuity_snapshots_episode ON continuity_snapshots(episode_id);
CREATE INDEX ix_continuity_snapshots_shot    ON continuity_snapshots(shot_id);

COMMIT;
