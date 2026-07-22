BEGIN;

CREATE TABLE analysis_documents (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  episode_id uuid REFERENCES episodes(id) ON DELETE CASCADE,
  source_stage_run_id uuid NOT NULL REFERENCES stage_runs(id) ON DELETE CASCADE,
  media_asset_id uuid NOT NULL REFERENCES media_assets(id) ON DELETE RESTRICT,
  document_type varchar(64) NOT NULL,
  schema_version integer NOT NULL DEFAULT 1 CHECK (schema_version >= 1),
  payload jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(source_stage_run_id, media_asset_id, document_type)
);
CREATE INDEX ix_analysis_documents_project_type
  ON analysis_documents(project_id, document_type);
CREATE INDEX ix_analysis_documents_payload_gin ON analysis_documents USING gin(payload);

COMMIT;
