-- Migration 0017: governance tables
-- audit_logs, cost_events, runtime_profiles

BEGIN;

-- audit_logs: immutable record of all config/approval/retry/deletion actions
CREATE TABLE audit_logs (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id    UUID        NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    project_id      UUID        REFERENCES projects(id) ON DELETE SET NULL,
    actor_id        UUID,           -- user or service account
    action          VARCHAR(128) NOT NULL,  -- e.g. "project.cancel", "model_release.approve"
    target_type     VARCHAR(64),
    target_id       UUID,
    -- Before/after snapshots (redact secrets before storing)
    before_state    JSONB,
    after_state     JSONB,
    reason          TEXT,
    ip_address      VARCHAR(45),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX ix_audit_logs_workspace   ON audit_logs(workspace_id, created_at DESC);
CREATE INDEX ix_audit_logs_project     ON audit_logs(project_id, created_at DESC)
    WHERE project_id IS NOT NULL;
CREATE INDEX ix_audit_logs_target      ON audit_logs(target_type, target_id)
    WHERE target_type IS NOT NULL;

-- cost_events: per-attempt cost attribution (GPU seconds, storage, external API)
CREATE TABLE cost_events (
    id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id        UUID        NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    project_id          UUID        NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    stage_run_id        UUID        REFERENCES stage_runs(id) ON DELETE SET NULL,
    stage_attempt_id    UUID        REFERENCES stage_attempts(id) ON DELETE SET NULL,
    event_type          VARCHAR(64) NOT NULL,  -- GPU_USAGE | STORAGE_WRITE | EXTERNAL_API | CANCELLED
    -- Provider (modal, s3, anthropic, etc.)
    provider            VARCHAR(64),
    -- Resource type and quantity
    resource_type       VARCHAR(64),  -- gpu_seconds, cpu_core_seconds, storage_gib_seconds
    quantity            NUMERIC(20, 6) NOT NULL DEFAULT 0,
    unit_price_usd      NUMERIC(14, 8) NOT NULL DEFAULT 0,
    total_usd           NUMERIC(14, 6) NOT NULL DEFAULT 0,
    -- GPU metadata
    gpu_type            VARCHAR(64),
    model_release_id    UUID,
    -- External API call ID for dedup
    provider_usage_id   VARCHAR(256) UNIQUE,
    occurred_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX ix_cost_events_project    ON cost_events(project_id, occurred_at DESC);
CREATE INDEX ix_cost_events_stage_run  ON cost_events(stage_run_id) WHERE stage_run_id IS NOT NULL;

-- runtime_profiles: immutable GPU-family/CUDA/framework/container config
-- Each model_release references a runtime_profile to enforce GPU compatibility.
CREATE TABLE runtime_profiles (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    profile_name    VARCHAR(128) NOT NULL UNIQUE,
    -- render-cuda12-mature | render-blackwell-validated | render-b300-cuda13
    profile_class   VARCHAR(64) NOT NULL,
    -- Supported GPU types (array of strings like ["L40S","A100","H100","H200"])
    supported_gpu_types JSONB   NOT NULL DEFAULT '[]',
    minimum_cuda_version VARCHAR(16) NOT NULL,
    -- Container image digest that was validated for this profile
    image_digest    VARCHAR(128),
    framework_versions  JSONB   NOT NULL DEFAULT '{}',  -- {torch, diffusers, ...}
    -- Validation results
    validated_at    TIMESTAMPTZ,
    validated_by    VARCHAR(128),
    notes           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_runtime_profiles_class
        CHECK (profile_class IN (
            'render-cuda12-mature',
            'render-blackwell-validated',
            'render-b300-cuda13',
            'cpu-standard',
            'audio-standard'
        ))
);

-- Seed the three GPU runtime profiles from §8.8
INSERT INTO runtime_profiles (profile_name, profile_class, supported_gpu_types,
    minimum_cuda_version, notes)
VALUES
    ('render-cuda12-mature', 'render-cuda12-mature',
     '["L40S","A100","H100","H200"]', '12.0',
     'Mature CUDA 12.x stack; L40S baseline, H200 for large-VRAM models'),
    ('render-blackwell-validated', 'render-blackwell-validated',
     '["B200"]', '12.4',
     'Blackwell B200 — must not share image with B300'),
    ('render-b300-cuda13', 'render-b300-cuda13',
     '["B300"]', '13.1',
     'EXPERIMENTAL — requires CUDA 13.1+; all deps must be rebuilt'),
    ('cpu-standard', 'cpu-standard',
     '[]', '0.0',
     'CPU-only workers: FFmpeg, Pillow, assembly'),
    ('audio-standard', 'audio-standard',
     '["L4","A10"]', '12.0',
     'Audio analysis and stem separation');

COMMIT;
