from uuid import uuid4

import modal
from vtv_orchestrator import ModalStageExecutor
from vtv_schemas.jobs import StageJob, StageResult


def _job() -> StageJob:
    return StageJob(
        stage_run_id=uuid4(),
        stage_attempt_id=uuid4(),
        project_id=uuid4(),
        idempotency_key="modal:test",
        stage_type="ASR_ALIGN",
        output_prefix="s3://bucket/output",
        runtime_profile_id="modal-test",
        observed_control_version=1,
        trace_id="modal-test",
    )


def test_modal_executor_validates_remote_result(monkeypatch) -> None:
    job = _job()
    expected = StageResult(
        stage_run_id=job.stage_run_id,
        stage_attempt_id=job.stage_attempt_id,
        status="OUTPUT_READY",
        attempt_usage={"worker": "modal"},
    )

    class Function:
        def remote(self, payload):
            assert payload["stage_type"] == "ASR_ALIGN"
            return expected.model_dump(mode="json")

    monkeypatch.setattr(modal.Function, "from_name", lambda *args, **kwargs: Function())

    assert ModalStageExecutor().execute(job) == expected


def test_modal_executor_rejects_mismatched_identity(monkeypatch) -> None:
    job = _job()

    class Function:
        def remote(self, payload):
            return StageResult(
                stage_run_id=uuid4(),
                stage_attempt_id=job.stage_attempt_id,
                status="OUTPUT_READY",
            ).model_dump(mode="json")

    monkeypatch.setattr(modal.Function, "from_name", lambda *args, **kwargs: Function())

    result = ModalStageExecutor().execute(job)

    assert result.status == "EXECUTION_FAILED"
    assert result.error_class == "ValueError"
    assert result.error_detail and result.error_detail["retryable"] is True
