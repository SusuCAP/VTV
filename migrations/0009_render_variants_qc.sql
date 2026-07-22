ALTER TABLE candidate_groups
    ADD COLUMN status VARCHAR(16) NOT NULL DEFAULT 'OPEN',
    ADD COLUMN state_version BIGINT NOT NULL DEFAULT 1,
    ADD CONSTRAINT ck_candidate_groups_status CHECK (status IN ('OPEN', 'ADOPTED')),
    ADD CONSTRAINT ck_candidate_groups_state_version CHECK (state_version >= 1);

CREATE TABLE render_variants (
    id UUID PRIMARY KEY,
    candidate_group_id UUID NOT NULL REFERENCES candidate_groups(id) ON DELETE CASCADE,
    stage_run_id UUID NOT NULL REFERENCES stage_runs(id) ON DELETE CASCADE,
    variant_no INTEGER NOT NULL CHECK (variant_no >= 1),
    status VARCHAR(16) NOT NULL DEFAULT 'GENERATED'
        CHECK (status IN ('GENERATED', 'QC_PASSED', 'QC_FAILED', 'REVIEW', 'ADOPTED', 'REJECTED')),
    seed BIGINT NULL,
    output_asset_id UUID NOT NULL REFERENCES media_assets(id) ON DELETE RESTRICT,
    raw_metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
    allocated_cost JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_render_variants_stage_number UNIQUE (stage_run_id, variant_no)
);

CREATE INDEX ix_render_variants_group_status
    ON render_variants(candidate_group_id, status);

ALTER TABLE candidate_groups
    ADD CONSTRAINT fk_candidate_groups_adopted_variant
    FOREIGN KEY (adopted_variant_id) REFERENCES render_variants(id) ON DELETE SET NULL;

CREATE TABLE qc_results (
    id UUID PRIMARY KEY,
    render_variant_id UUID NOT NULL REFERENCES render_variants(id) ON DELETE CASCADE,
    metric_name VARCHAR(100) NOT NULL,
    metric_version VARCHAR(100) NOT NULL,
    evaluator_release VARCHAR(200) NOT NULL,
    score DOUBLE PRECISION NOT NULL CHECK (score BETWEEN 0 AND 1),
    verdict VARCHAR(16) NOT NULL CHECK (verdict IN ('PASS', 'FAIL', 'REVIEW')),
    hard_failure BOOLEAN NOT NULL DEFAULT FALSE,
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_qc_result_metric
        UNIQUE (render_variant_id, metric_name, metric_version, evaluator_release)
);

CREATE INDEX ix_qc_results_variant_verdict
    ON qc_results(render_variant_id, verdict);
