from vtv_schemas.jobs import StageJob, StageResult


def execute(job: StageJob) -> StageResult:
    """Deterministic worker used by local and CI end-to-end orchestration tests."""
    if job.params.get("force_failure"):
        return StageResult(
            stage_run_id=job.stage_run_id,
            stage_attempt_id=job.stage_attempt_id,
            status="EXECUTION_FAILED",
            error_class="MOCK_FAILURE",
            error_detail={"retryable": True},
        )
    return StageResult(
        stage_run_id=job.stage_run_id,
        stage_attempt_id=job.stage_attempt_id,
        status="OUTPUT_READY",
        attempt_usage={"cpu_core_seconds": 0.01, "worker": "mock"},
    )
