-- Migration 0013: project archive support
-- Add archived_at and archive_reason columns to projects table.
-- Archived projects are excluded from list_projects by default.

ALTER TABLE projects
    ADD COLUMN archived_at TIMESTAMPTZ,
    ADD COLUMN archive_reason VARCHAR(500);

CREATE INDEX ix_projects_archived ON projects(workspace_id, archived_at)
    WHERE archived_at IS NOT NULL;
