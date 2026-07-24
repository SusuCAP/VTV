-- Migration 0022: users table + render_variants ADOPTED partial unique index
-- Adds the users/members table required by §13.1 (workspaces/users)
-- and the one-adopted-per-candidate-group constraint required by §13.3.

BEGIN;

-- ── users table ──────────────────────────────────────────────────────────────
-- Platform users and their workspace membership.
-- In research/personal mode a single implicit admin user is sufficient;
-- the table structure allows multi-user workspaces for future expansion.
CREATE TABLE users (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id    UUID        NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    email           VARCHAR(320) NOT NULL,
    display_name    VARCHAR(200),
    role            VARCHAR(32) NOT NULL DEFAULT 'developer'
        CONSTRAINT ck_users_role CHECK (role IN ('admin', 'developer', 'viewer')),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_users_workspace_email UNIQUE (workspace_id, email)
);

CREATE INDEX ix_users_workspace ON users(workspace_id);
CREATE INDEX ix_users_email     ON users(email);

-- ── render_variants ADOPTED partial unique index ──────────────────────────────
-- §13.3 MANDATORY constraint: only one variant per candidate_group may be in
-- the ADOPTED state.  This enforces the idempotent "last-writer-wins" adoption
-- rule at the database level and prevents concurrent workers from double-adopting.
CREATE UNIQUE INDEX IF NOT EXISTS one_adopted_variant_per_group
    ON render_variants(candidate_group_id)
    WHERE status = 'ADOPTED';

COMMIT;
