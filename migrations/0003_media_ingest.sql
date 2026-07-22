BEGIN;

CREATE TABLE upload_sessions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  episode_no integer CHECK (episode_no IS NULL OR episode_no >= 1),
  filename varchar(255) NOT NULL,
  content_type varchar(200) NOT NULL,
  size_bytes bigint NOT NULL CHECK (size_bytes > 0),
  part_size_bytes bigint NOT NULL CHECK (part_size_bytes BETWEEN 33554432 AND 134217728),
  declared_sha256 varchar(64) NOT NULL CHECK (declared_sha256 ~ '^[a-f0-9]{64}$'),
  object_key text NOT NULL UNIQUE,
  provider_upload_id text NOT NULL,
  status varchar(32) NOT NULL DEFAULT 'UPLOADING',
  completed_parts jsonb NOT NULL DEFAULT '[]',
  object_checksum_sha256 varchar(64),
  episode_id uuid REFERENCES episodes(id) ON DELETE SET NULL,
  media_asset_id uuid REFERENCES media_assets(id) ON DELETE SET NULL,
  ingest_job_id uuid REFERENCES jobs(id) ON DELETE SET NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(workspace_id, provider_upload_id)
);
CREATE INDEX ix_upload_sessions_project_status ON upload_sessions(project_id, status);

ALTER TABLE media_assets
  ADD CONSTRAINT ck_media_assets_sha256 CHECK (sha256 ~ '^[a-f0-9]{64}$'),
  ADD CONSTRAINT ck_media_assets_size CHECK (size_bytes > 0);

ALTER TABLE episodes
  ADD CONSTRAINT fk_episodes_source_asset_id
  FOREIGN KEY (source_asset_id) REFERENCES media_assets(id) ON DELETE SET NULL;

COMMIT;
