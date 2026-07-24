from uuid import uuid4

import modal
from vtv_orchestrator import ModalStageExecutor, ModalStageGateway
from vtv_orchestrator.modal_executor import modal_workload_json
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

    class Method:
        def remote(self, payload):
            assert payload["stage_type"] == "ASR_ALIGN"
            return expected.model_dump(mode="json")

    class Worker:
        def __init__(self, **kwargs):
            assert kwargs == {
                "stage_type": "ASR_ALIGN",
                "runtime_json": "{}",
                "workload_json": '{"reference_count":0}',
            }
            self.run = Method()

    monkeypatch.setattr(modal.Cls, "from_name", lambda *args, **kwargs: Worker)

    assert ModalStageExecutor().execute(job) == expected


def test_modal_executor_rejects_mismatched_identity(monkeypatch) -> None:
    job = _job()

    class Method:
        def remote(self, payload):
            return StageResult(
                stage_run_id=uuid4(),
                stage_attempt_id=job.stage_attempt_id,
                status="OUTPUT_READY",
            ).model_dump(mode="json")

    class Worker:
        def __init__(self, **kwargs):
            self.run = Method()

    monkeypatch.setattr(modal.Cls, "from_name", lambda *args, **kwargs: Worker)

    result = ModalStageExecutor().execute(job)

    assert result.status == "EXECUTION_FAILED"
    assert result.error_class == "ValueError"
    assert result.error_detail and result.error_detail["retryable"] is True


def test_modal_gateway_canonicalizes_runtime_for_class_binding(monkeypatch) -> None:
    job = _job().model_copy(
        update={"params": {"model_runtime": {"release": "asr@1", "config": {"b": 2, "a": 1}}}}
    )
    captured: dict[str, object] = {}

    class Call:
        object_id = "fc-123"

    class Method:
        def spawn(self, payload):
            captured["payload"] = payload
            return Call()

    class Worker:
        def __init__(self, **kwargs):
            captured["binding"] = kwargs
            self.run = Method()

    def from_name(app_name, class_name, **kwargs):
        captured["target"] = (app_name, class_name, kwargs)
        return Worker

    monkeypatch.setattr(modal.Cls, "from_name", from_name)

    assert ModalStageGateway(environment_name="test").spawn(job) == "fc-123"
    assert captured["target"] == (
        "vtv-audio",
        "AudioStageWorker",
        {"environment_name": "test"},
    )
    assert captured["binding"] == {
        "stage_type": "ASR_ALIGN",
        "runtime_json": '{"config":{"a":1,"b":2},"release":"asr@1"}',
        "workload_json": '{"reference_count":0}',
    }
    assert captured["payload"]["stage_attempt_id"] == str(job.stage_attempt_id)


def test_modal_gateway_uses_function_target_for_assemble(monkeypatch) -> None:
    job = _job().model_copy(update={"stage_type": "ASSEMBLE_EPISODE"})
    captured: dict[str, object] = {}

    class Call:
        object_id = "fc-assemble"

    class Function:
        def spawn(self, payload):
            captured["payload"] = payload
            return Call()

    def from_name(app_name, function_name, **kwargs):
        captured["target"] = (app_name, function_name, kwargs)
        return Function()

    monkeypatch.setattr(modal.Function, "from_name", from_name)

    assert ModalStageGateway().spawn(job) == "fc-assemble"
    assert captured["target"] == (
        "vtv-assemble",
        "execute_assemble_stage",
        {"environment_name": None},
    )


def test_modal_workload_key_captures_pool_sizing_dimensions() -> None:
    job = _job().model_copy(
        update={
            "params": {
                "model_runtime": {
                    "config": {
                        "target_resolution": "720p",
                        "target_frame_count": 81,
                    }
                },
                "visual_generation_request": {
                    "reference_asset_sha256s": ["a" * 64, "b" * 64],
                },
            }
        }
    )

    assert modal_workload_json(job) == (
        '{"frame_count":81,"reference_count":2,"resolution":"720p"}'
    )
