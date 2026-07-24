-- Migration 0014: characters, character_releases, look_states
-- Persists cross-episode character clustering and localization asset versions.

BEGIN;

CREATE TABLE characters (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id  UUID        NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    display_name VARCHAR(200) NOT NULL,
    -- Localized name chosen for target market
    localized_name VARCHAR(200),
    gender      VARCHAR(32),
    -- Cluster fingerprint: hash of merged face embeddings
    cluster_fingerprint VARCHAR(64),
    -- Manually confirmed by human reviewer
    confirmed   BOOLEAN     NOT NULL DEFAULT FALSE,
    notes       TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX ix_characters_project ON characters(project_id);
CREATE INDEX ix_characters_project_confirmed ON characters(project_id, confirmed);

CREATE TABLE character_releases (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id      UUID        NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    character_id    UUID        NOT NULL REFERENCES characters(id) ON DELETE CASCADE,
    version         INTEGER     NOT NULL DEFAULT 1,
    -- DRAFT → CONFIRMED → RELEASED (follows ArtifactRelease lifecycle)
    status          VARCHAR(32) NOT NULL DEFAULT 'DRAFT',
    -- S3 URI to anchor pack JSON (character reference images, voice samples)
    anchor_pack_uri VARCHAR(2048),
    anchor_pack_sha256 VARCHAR(64),
    -- Model releases used to generate this anchor pack
    model_release_ids JSONB     NOT NULL DEFAULT '[]',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_character_releases_version UNIQUE (character_id, version),
    CONSTRAINT ck_character_releases_version CHECK (version >= 1),
    CONSTRAINT ck_character_releases_status
        CHECK (status IN ('DRAFT', 'CONFIRMED', 'RELEASED', 'SUPERSEDED'))
);

CREATE INDEX ix_character_releases_project ON character_releases(project_id, status);

-- LookState: per-episode costume state for a character
-- Captures hair/makeup/clothing/wounds/accessories at a point in the episode timeline.
CREATE TABLE look_states (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    character_id    UUID        NOT NULL REFERENCES characters(id) ON DELETE CASCADE,
    episode_id      UUID        NOT NULL REFERENCES episodes(id) ON DELETE CASCADE,
    -- Shot number range this look is active over
    first_shot_no   INTEGER     NOT NULL,
    last_shot_no    INTEGER,
    -- Structured state: {hair, makeup, clothing, wounds, accessories, notes}
    state_payload   JSONB       NOT NULL DEFAULT '{}',
    -- S3 URI to representative reference image
    reference_uri   VARCHAR(2048),
    confirmed       BOOLEAN     NOT NULL DEFAULT FALSE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX ix_look_states_character ON look_states(character_id);
CREATE INDEX ix_look_states_episode   ON look_states(episode_id);

COMMIT;
