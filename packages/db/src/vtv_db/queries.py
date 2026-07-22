from sqlalchemy import text

CLAIM_READY_STAGE = text(
    """
    WITH candidate AS (
      SELECT sr.id
      FROM stage_runs sr
      JOIN execution_controls ec ON ec.project_id = sr.project_id
      WHERE sr.status = 'READY'
        AND sr.available_at <= now()
        AND NOT ec.paused
        AND NOT ec.cancel_requested
        AND NOT ec.hard_budget_blocked
        AND NOT EXISTS (
          SELECT 1 FROM deletion_tombstones dt
          WHERE dt.resource_type = 'project' AND dt.resource_id = sr.project_id
        )
        AND NOT EXISTS (
          SELECT 1
          FROM stage_dependencies sd
          JOIN stage_runs upstream ON upstream.id = sd.depends_on_stage_run_id
          WHERE sd.stage_run_id = sr.id
            AND upstream.status NOT IN ('COMPLETED', 'ADOPTED')
        )
      ORDER BY sr.priority DESC, sr.available_at, sr.created_at
      FOR UPDATE SKIP LOCKED
      LIMIT 1
    )
    UPDATE stage_runs sr
    SET status = 'RUNNING',
        lease_owner = :lease_owner,
        lease_expires_at = now() + make_interval(secs => :lease_seconds),
        state_version = state_version + 1,
        updated_at = now()
    FROM candidate
    WHERE sr.id = candidate.id
    RETURNING sr.*
    """
)


COMMIT_OUTPUT_READY = text(
    """
    UPDATE stage_runs sr
    SET status = 'OUTPUT_READY', state_version = state_version + 1, updated_at = now()
    FROM stage_attempts sa, execution_controls ec
    WHERE sr.id = :stage_run_id
      AND sa.id = :stage_attempt_id
      AND sa.stage_run_id = sr.id
      AND sa.lease_token = :lease_token
      AND sr.status = 'RUNNING'
      AND sr.state_version = :expected_state_version
      AND sr.lease_expires_at > now()
      AND ec.project_id = sr.project_id
      AND ec.control_version = :observed_control_version
      AND NOT ec.cancel_requested
      AND NOT EXISTS (
        SELECT 1 FROM deletion_tombstones dt
        WHERE dt.resource_type = 'project' AND dt.resource_id = sr.project_id
      )
    RETURNING sr.id, sr.state_version
    """
)
