-- Migration 0021: model_capability_profiles and model_access_profiles

CREATE TABLE model_capability_profiles (
    id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    model_release_id      UUID NOT NULL UNIQUE REFERENCES model_releases(id),
    capabilities          JSONB NOT NULL DEFAULT '[]',
    supported_resolutions JSONB NOT NULL DEFAULT '[]',
    max_frame_count       INT,
    reference_input_types JSONB NOT NULL DEFAULT '[]',
    conditioning_types    JSONB NOT NULL DEFAULT '[]',
    known_limitations     TEXT,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE model_access_profiles (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    model_release_id        UUID NOT NULL UNIQUE REFERENCES model_releases(id),
    weight_download_url     VARCHAR(2048),
    weight_sha256           VARCHAR(64),
    checkpoint_filename     VARCHAR(512),
    required_packages       JSONB NOT NULL DEFAULT '[]',
    min_cuda_version        VARCHAR(16) NOT NULL,
    min_vram_gib            INT,
    reproducibility_config  JSONB NOT NULL DEFAULT '{}',
    availability_status     VARCHAR(32) NOT NULL DEFAULT 'UNRELEASED' CHECK (availability_status IN (
                                'AVAILABLE',
                                'GATED',
                                'UNRELEASED',
                                'BROKEN',
                                'OOM_RISK'
                            )),
    verified_at             TIMESTAMPTZ,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
