BEGIN;

CREATE TABLE artifact_releases (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  artifact_type varchar(64) NOT NULL,
  version integer NOT NULL CHECK (version >= 1),
  status varchar(32) NOT NULL DEFAULT 'DRAFT'
    CHECK (status IN ('DRAFT', 'CONFIRMED', 'RELEASED', 'STALE')),
  state_version bigint NOT NULL DEFAULT 1 CHECK (state_version >= 1),
  content_asset_id uuid NOT NULL REFERENCES media_assets(id) ON DELETE RESTRICT,
  supersedes_release_id uuid REFERENCES artifact_releases(id) ON DELETE SET NULL,
  confirmed_by uuid,
  confirmed_at timestamptz,
  released_at timestamptz,
  stale_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(project_id, artifact_type, version)
);
CREATE INDEX ix_artifact_releases_project_type_status
  ON artifact_releases(project_id, artifact_type, status);

CREATE TABLE artifact_release_dependencies (
  upstream_release_id uuid NOT NULL REFERENCES artifact_releases(id) ON DELETE CASCADE,
  downstream_release_id uuid NOT NULL REFERENCES artifact_releases(id) ON DELETE CASCADE,
  PRIMARY KEY (upstream_release_id, downstream_release_id),
  CHECK (upstream_release_id <> downstream_release_id)
);

COMMIT;
