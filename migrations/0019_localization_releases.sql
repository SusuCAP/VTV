-- Migration 0019: localization_releases

CREATE TABLE localization_releases (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id           UUID NOT NULL REFERENCES projects(id),
    version              INT NOT NULL DEFAULT 1,
    status               VARCHAR(32) NOT NULL CHECK (status IN (
                             'DRAFT',
                             'CONFIRMED',
                             'RELEASED',
                             'SUPERSEDED'
                         )),
    target_market        VARCHAR(16) NOT NULL,
    locale               VARCHAR(35) NOT NULL,
    rules_payload        JSONB NOT NULL DEFAULT '{}',
    terminology_payload  JSONB NOT NULL DEFAULT '{}',
    fingerprint          VARCHAR(64),
    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (project_id, version)
);
