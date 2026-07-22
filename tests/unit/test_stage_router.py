from pathlib import Path
from uuid import uuid4

from vtv_orchestrator.stage_router import StageRouter
from vtv_schemas.jobs import StageJob, StageResult


def _job(stage_type: str) -> StageJob:
    return StageJob(
        stage_run_id=uuid4(),
        stage_attempt_id=uuid4(),
        project_id=uuid4(),
        idempotency_key=f"test:{stage_type}",
        stage_type=stage_type,
        output_prefix="memory://old",
        runtime_profile_id="test",
        observed_control_version=1,
        trace_id="router-test",
    )


def _successful(job: StageJob) -> StageResult:
    return StageResult(
        stage_run_id=job.stage_run_id,
        stage_attempt_id=job.stage_attempt_id,
        status="OUTPUT_READY",
        attempt_usage={"output_prefix": job.output_prefix},
    )


def test_router_sends_concrete_stages_to_local_workers(tmp_path: Path) -> None:
    router = StageRouter(
        tmp_path,
        media_executor=_successful,
        analysis_executor=_successful,
        fallback_executor=_successful,
    )

    media = router.execute(_job("PROXY_GENERATE"))
    analysis = router.execute(_job("ASR_ALIGN"))
    fallback = router.execute(_job("MOCK_RENDER"))

    assert media.attempt_usage["output_prefix"].startswith("file://")
    assert analysis.attempt_usage["output_prefix"].startswith("file://")
    assert fallback.attempt_usage["output_prefix"] == "memory://old"


def test_router_converts_worker_exception_to_stage_failure(tmp_path: Path) -> None:
    def fail(job: StageJob) -> StageResult:
        raise RuntimeError(f"cannot execute {job.stage_type}")

    result = StageRouter(tmp_path, media_executor=fail).execute(_job("SHOT_DETECT"))

    assert result.status == "EXECUTION_FAILED"
    assert result.error_class == "RuntimeError"
    assert result.error_detail == {
        "message": "cannot execute SHOT_DETECT",
        "retryable": False,
    }
