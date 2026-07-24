-- Migration 0018: workflow_plans and review_tasks

CREATE TABLE workflow_plans (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id          UUID NOT NULL REFERENCES projects(id),
    episode_id          UUID REFERENCES episodes(id),
    shot_id             UUID REFERENCES shots(id),
    plan_version        INT NOT NULL DEFAULT 1,
    route               VARCHAR(2) NOT NULL,
    reason_codes        JSONB NOT NULL DEFAULT '[]',
    estimated_cost_usd  NUMERIC(10,4),
    model_release_id    UUID,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (shot_id, plan_version)
);

CREATE TABLE review_tasks (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id    UUID NOT NULL REFERENCES workspaces(id),
    project_id      UUID NOT NULL REFERENCES projects(id),
    task_type       VARCHAR(64) NOT NULL CHECK (task_type IN (
                        'CHARACTER_CONFIRMATION',
                        'SCENE_CONFIRMATION',
                        'DIALOGUE_REVIEW',
                        'EXCEPTION_SHOT',
                        'FINAL_SPOT_CHECK'
                    )),
    status          VARCHAR(32) NOT NULL CHECK (status IN (
                        'PENDING',
                        'ASSIGNED',
                        'DONE',
                        'SKIPPED'
                    )),
    assignee_id     UUID,
    shot_id         UUID,
    episode_id      UUID,
    payload         JSONB NOT NULL DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_review_tasks_project_status ON review_tasks (project_id, status);
CREATE INDEX idx_review_tasks_status_assignee ON review_tasks (status, assignee_id);
