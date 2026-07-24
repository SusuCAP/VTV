-- Bind every Stage Run to an immutable runtime_profiles row.
-- The legacy runtime_profile_id names are retained for wire compatibility;
-- runtime_profile_uuid is the database authority.

BEGIN;

ALTER TABLE stage_runs
    ADD COLUMN runtime_profile_uuid UUID;

UPDATE stage_runs AS sr
SET runtime_profile_uuid = rp.id
FROM runtime_profiles AS rp
WHERE rp.profile_name = CASE sr.runtime_profile_id
    WHEN 'cpu-standard' THEN 'cpu-standard'
    WHEN 'cpu-media' THEN 'cpu-standard'
    WHEN 'cpu-assemble' THEN 'cpu-standard'
    WHEN 'gpu-audio' THEN 'audio-standard'
    WHEN 'gpu-analysis' THEN 'render-cuda12-mature'
    WHEN 'gpu-visual' THEN 'render-cuda12-mature'
    WHEN 'gpu-render' THEN 'render-cuda12-mature'
    ELSE sr.runtime_profile_id
END;

CREATE OR REPLACE FUNCTION resolve_stage_runtime_profile()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.runtime_profile_uuid IS NULL THEN
        SELECT id
        INTO NEW.runtime_profile_uuid
        FROM runtime_profiles
        WHERE profile_name = CASE NEW.runtime_profile_id
            WHEN 'cpu-media' THEN 'cpu-standard'
            WHEN 'cpu-assemble' THEN 'cpu-standard'
            WHEN 'gpu-audio' THEN 'audio-standard'
            WHEN 'gpu-analysis' THEN 'render-cuda12-mature'
            WHEN 'gpu-visual' THEN 'render-cuda12-mature'
            WHEN 'gpu-render' THEN 'render-cuda12-mature'
            ELSE NEW.runtime_profile_id
        END;
    END IF;
    IF NEW.runtime_profile_uuid IS NULL THEN
        RAISE EXCEPTION 'unknown runtime profile: %', NEW.runtime_profile_id;
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_stage_runs_runtime_profile
    BEFORE INSERT OR UPDATE OF runtime_profile_id, runtime_profile_uuid
    ON stage_runs
    FOR EACH ROW EXECUTE FUNCTION resolve_stage_runtime_profile();

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM stage_runs WHERE runtime_profile_uuid IS NULL) THEN
        RAISE EXCEPTION
            'stage_runs contains runtime profiles without a runtime_profiles registry row';
    END IF;
END $$;

ALTER TABLE stage_runs
    ALTER COLUMN runtime_profile_uuid SET NOT NULL,
    ADD CONSTRAINT fk_stage_runs_runtime_profile
        FOREIGN KEY (runtime_profile_uuid) REFERENCES runtime_profiles(id);

CREATE INDEX ix_stage_runs_runtime_profile
    ON stage_runs(runtime_profile_uuid);

COMMIT;
