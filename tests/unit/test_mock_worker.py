from uuid import uuid4

from vtv_orchestrator.mock_worker import execute
from vtv_schemas.jobs import StageJob


def make_job(**params: object) -> StageJob:
    return StageJob(
        stage_run_id=uuid4(),
        stage_attempt_id=uuid4(),
        project_id=uuid4(),
        idempotency_key="test",
        stage_type="INGEST_VALIDATE",
        output_prefix="memory://output",
        runtime_profile_id="cpu-media",
        observed_control_version=1,
        params=params,
        trace_id="trace-test",
    )


def test_mock_worker_returns_output_ready() -> None:
    result = execute(make_job())
    assert result.status == "OUTPUT_READY"
    assert result.attempt_usage["worker"] == "mock"
    assert result.variants[0].output_assets[0].uri.endswith("result.json")
    assert len(result.variants[0].output_assets[0].sha256) == 64


def test_mock_worker_supports_retryable_failure() -> None:
    result = execute(make_job(force_failure=True))
    assert result.status == "EXECUTION_FAILED"
    assert result.error_detail == {"retryable": True}
