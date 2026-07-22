from uuid import uuid4

import pytest
from vtv_production_worker.config import Settings
from vtv_production_worker.factory import create_production_worker_for_job
from vtv_schemas.jobs import StageJob


def _job(config: dict) -> StageJob:
    return StageJob(
        stage_run_id=uuid4(),
        stage_attempt_id=uuid4(),
        project_id=uuid4(),
        idempotency_key="tts:runtime",
        stage_type="TTS_GENERATE",
        output_prefix="file:///tmp/tts-output",
        runtime_profile_id="gpu-audio",
        observed_control_version=1,
        params={
            "model_runtime": {
                "endpoint": "https://tts.example.invalid/v1/synthesize",
                "release": "voxcpm2@approved-4",
                "license_id": "license-4",
                "approved_for_automation": True,
                "config": config,
            }
        },
        trace_id="tts-runtime-test",
    )


def test_registry_runtime_constructs_remote_tts_adapter_without_loading_model() -> None:
    worker = create_production_worker_for_job(
        _job({"adapter_mode": "remote_tts"}),
        Settings(tts_token="secret-for-test"),
    )

    assert worker.tts.model_release == "voxcpm2@approved-4"
    assert worker.tts.config.bearer_token == "secret-for-test"


def test_tts_factory_rejects_unregistered_or_wrong_adapter_mode() -> None:
    job = _job({"adapter_mode": "unknown"})
    with pytest.raises(ValueError, match="must select remote_tts"):
        create_production_worker_for_job(job, Settings())

    with pytest.raises(ValueError, match="Registry-selected"):
        create_production_worker_for_job(
            job.model_copy(update={"params": {}}), Settings()
        )


def test_registry_runtime_constructs_remote_lipsync_adapter() -> None:
    job = _job({"adapter_mode": "remote_lipsync"}).model_copy(
        update={
            "stage_type": "LIPSYNC_GENERATE",
            "idempotency_key": "lipsync:runtime",
        }
    )
    worker = create_production_worker_for_job(
        job,
        Settings(lipsync_token="lipsync-secret", lipsync_timeout_seconds=900),
    )

    assert worker.lipsync.model_release == "voxcpm2@approved-4"
    assert worker.lipsync.config.bearer_token == "lipsync-secret"
    assert worker.lipsync.config.timeout_seconds == 900


def test_l0_lipsync_factory_uses_local_passthrough_without_registry_runtime() -> None:
    job = _job({}).model_copy(
        update={
            "stage_type": "LIPSYNC_GENERATE",
            "idempotency_key": "lipsync:l0",
            "params": {"lipsync_request": {"decision": {"level": "L0_NONE"}}},
        }
    )

    worker = create_production_worker_for_job(job, Settings())

    assert worker.lipsync.model_release == "lipsync-passthrough@1"
