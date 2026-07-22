BEGIN;

CREATE TABLE model_releases (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  model_key varchar(64) NOT NULL,
  release_name varchar(200) NOT NULL,
  provider varchar(100) NOT NULL,
  endpoint text NOT NULL,
  license_id varchar(200) NOT NULL,
  license_status varchar(32) NOT NULL DEFAULT 'REVIEW'
    CHECK (license_status IN ('REVIEW', 'APPROVED', 'REJECTED')),
  automation_status varchar(32) NOT NULL DEFAULT 'OBSERVE'
    CHECK (automation_status IN ('OBSERVE', 'CANARY', 'ACTIVE', 'DISABLED')),
  traffic_percent integer NOT NULL DEFAULT 0 CHECK (traffic_percent BETWEEN 0 AND 100),
  state_version bigint NOT NULL DEFAULT 1 CHECK (state_version >= 1),
  model_card_uri text NOT NULL,
  config jsonb NOT NULL DEFAULT '{}',
  fallback_release_id uuid REFERENCES model_releases(id) ON DELETE SET NULL,
  reviewed_by uuid,
  reviewed_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(workspace_id, model_key, release_name)
);
CREATE INDEX ix_model_releases_workspace_key_status
  ON model_releases(workspace_id, model_key, automation_status);

ALTER TABLE stage_runs
  ADD CONSTRAINT fk_stage_runs_model_release_id
  FOREIGN KEY (model_release_id) REFERENCES model_releases(id) ON DELETE SET NULL;

COMMIT;
