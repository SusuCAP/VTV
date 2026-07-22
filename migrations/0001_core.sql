BEGIN;

CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- SQLAlchemy metadata in packages/db is the application model. This migration is
-- deliberately explicit so production bootstrap does not depend on runtime DDL.
CREATE TABLE workspaces (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name varchar(200) NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE projects (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  name varchar(200) NOT NULL,
  target_market varchar(16) NOT NULL,
  locale varchar(35) NOT NULL,
  timezone varchar(64) NOT NULL DEFAULT 'UTC',
  quality_profile varchar(64) NOT NULL,
  status varchar(40) NOT NULL DEFAULT 'DRAFT',
  state_version bigint NOT NULL DEFAULT 1,
  budget_currency varchar(3) NOT NULL DEFAULT 'USD',
  budget_warning_at numeric(14,4) NOT NULL CHECK (budget_warning_at >= 0),
  budget_hard_limit numeric(14,4) NOT NULL CHECK (budget_hard_limit > 0),
  output_spec jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK (budget_warning_at <= budget_hard_limit)
);
CREATE INDEX ix_projects_workspace_status ON projects(workspace_id, status);

CREATE TABLE episodes (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  episode_no integer NOT NULL, title varchar(200), source_asset_id uuid, duration_ms bigint,
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(project_id, episode_no)
);
CREATE TABLE shots (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), episode_id uuid NOT NULL REFERENCES episodes(id) ON DELETE CASCADE,
  shot_no integer NOT NULL, start_ms bigint NOT NULL, end_ms bigint NOT NULL, route varchar(8), reason_codes jsonb NOT NULL DEFAULT '[]',
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(episode_id, shot_no), CHECK(end_ms > start_ms)
);
CREATE TABLE execution_controls (
  project_id uuid PRIMARY KEY REFERENCES projects(id) ON DELETE CASCADE,
  control_version bigint NOT NULL DEFAULT 1, paused boolean NOT NULL DEFAULT false,
  cancel_requested boolean NOT NULL DEFAULT false, hard_budget_blocked boolean NOT NULL DEFAULT false,
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE candidate_groups (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  shot_id uuid REFERENCES shots(id) ON DELETE CASCADE, purpose varchar(64) NOT NULL,
  adopted_variant_id uuid UNIQUE, created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE stage_runs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  episode_id uuid REFERENCES episodes(id) ON DELETE CASCADE, shot_id uuid REFERENCES shots(id) ON DELETE CASCADE,
  candidate_group_id uuid REFERENCES candidate_groups(id) ON DELETE SET NULL, stage_type varchar(64) NOT NULL,
  status varchar(32) NOT NULL DEFAULT 'PENDING', idempotency_key varchar(255) NOT NULL,
  model_release_id uuid, runtime_profile_id varchar(100) NOT NULL, state_version bigint NOT NULL DEFAULT 1,
  observed_control_version bigint NOT NULL, priority integer NOT NULL DEFAULT 0, available_at timestamptz NOT NULL DEFAULT now(),
  lease_owner varchar(200), lease_expires_at timestamptz, params jsonb NOT NULL DEFAULT '{}',
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(project_id, idempotency_key)
);
CREATE INDEX ix_stage_runs_claim ON stage_runs(status, available_at, priority DESC);
CREATE TABLE stage_dependencies (
  stage_run_id uuid NOT NULL REFERENCES stage_runs(id) ON DELETE CASCADE,
  depends_on_stage_run_id uuid NOT NULL REFERENCES stage_runs(id) ON DELETE CASCADE,
  PRIMARY KEY(stage_run_id, depends_on_stage_run_id), CHECK(stage_run_id <> depends_on_stage_run_id)
);
CREATE TABLE stage_attempts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), stage_run_id uuid NOT NULL REFERENCES stage_runs(id) ON DELETE CASCADE,
  attempt_no integer NOT NULL, status varchar(32) NOT NULL DEFAULT 'RUNNING', modal_call_id varchar(200), worker_id varchar(200),
  lease_token uuid NOT NULL DEFAULT gen_random_uuid(), started_at timestamptz NOT NULL DEFAULT now(), finished_at timestamptz,
  usage jsonb NOT NULL DEFAULT '{}', cost_usd numeric(14,6), error_class varchar(100), error_detail jsonb,
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(), UNIQUE(stage_run_id, attempt_no)
);
CREATE TABLE media_assets (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE, source_stage_run_id uuid REFERENCES stage_runs(id) ON DELETE SET NULL,
  object_uri text NOT NULL, sha256 varchar(64) NOT NULL, size_bytes bigint NOT NULL, content_type varchar(200) NOT NULL,
  metadata jsonb NOT NULL DEFAULT '{}', created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(workspace_id, sha256, object_uri)
);
CREATE TABLE orphan_assets (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  stage_attempt_id uuid REFERENCES stage_attempts(id) ON DELETE SET NULL, object_uri text NOT NULL, reason varchar(100) NOT NULL,
  delete_after timestamptz NOT NULL, created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE outbox_events (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), workspace_id uuid NOT NULL, aggregate_type varchar(64) NOT NULL,
  aggregate_id uuid NOT NULL, event_type varchar(100) NOT NULL, payload jsonb NOT NULL,
  published_at timestamptz, publish_attempts integer NOT NULL DEFAULT 0,
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_outbox_unpublished ON outbox_events(published_at, created_at);
CREATE TABLE deletion_tombstones (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), resource_type varchar(64) NOT NULL, resource_id uuid NOT NULL,
  requested_by uuid, reason text, created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(resource_type, resource_id)
);

COMMIT;
