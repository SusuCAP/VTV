BEGIN;

CREATE TABLE jobs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  kind varchar(64) NOT NULL,
  status varchar(32) NOT NULL DEFAULT 'QUEUED',
  idempotency_key varchar(255) NOT NULL,
  total_stages integer NOT NULL DEFAULT 0,
  completed_stages integer NOT NULL DEFAULT 0,
  error_detail jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(project_id, idempotency_key),
  CHECK(completed_stages >= 0 AND completed_stages <= total_stages)
);
CREATE INDEX ix_jobs_project_status ON jobs(project_id, status);

ALTER TABLE stage_runs
  ADD COLUMN job_id uuid REFERENCES jobs(id) ON DELETE CASCADE;
CREATE INDEX ix_stage_runs_job_status ON stage_runs(job_id, status);

COMMIT;
