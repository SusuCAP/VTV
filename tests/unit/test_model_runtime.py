from pathlib import Path
from uuid import uuid4

import pytest
from vtv_analysis import (
    AudioAnalysisPipeline,
    DeterministicAsr,
    DeterministicDiarization,
    DeterministicVad,
)
from vtv_analysis_worker.config import Settings
from vtv_analysis_worker.factory import create_analysis_worker, create_analysis_worker_for_job
from vtv_analysis_worker.runtime import (
    FallbackAudioAnalysisPipeline,
    ModelAccessDeniedError,
    ModelEndpoint,
    RemoteAudioAnalysisPipeline,
    RemoteInferenceError,
)
from vtv_schemas.jobs import StageJob


class FakeTransport:
    def __init__(self, response: dict | Exception) -> None:
        self.response = response
        self.calls = 0

    def post_media(
        self, config: ModelEndpoint, media: Path, payload: dict
    ) -> dict:
        self.calls += 1
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def _endpoint(**updates: object) -> ModelEndpoint:
    values = {
        "endpoint": "https://models.example.test/audio",
        "release": "audio-prod@7",
        "license_id": "license-record-1",
        "approved_for_automation": True,
    }
    values.update(updates)
    return ModelEndpoint(**values)


def test_remote_audio_pipeline_enforces_gate_before_transport(tmp_path: Path) -> None:
    media = tmp_path / "audio.wav"
    media.write_bytes(b"audio")
    transport = FakeTransport({})
    pipeline = RemoteAudioAnalysisPipeline(
        _endpoint(approved_for_automation=False), transport
    )

    with pytest.raises(ModelAccessDeniedError, match="not approved"):
        pipeline.analyze(media.resolve().as_uri(), 1, "zh-CN")
    assert transport.calls == 0


def test_remote_audio_pipeline_validates_typed_response_and_release(tmp_path: Path) -> None:
    media = tmp_path / "audio.wav"
    media.write_bytes(b"audio")
    pipeline = RemoteAudioAnalysisPipeline(
        _endpoint(),
        FakeTransport(
            {
                "analysis": {
                    "duration_seconds": 1,
                    "language": "zh-CN",
                    "speech": [],
                    "transcript": [],
                    "speakers": [],
                }
            }
        ),
    )

    result = pipeline.analyze(media.resolve().as_uri(), 1, "zh-CN")

    assert result.language == "zh-CN"
    assert pipeline.asr.model_release == "audio-prod@7:asr-align"


def test_explicit_fallback_records_actual_deterministic_release(tmp_path: Path) -> None:
    media = tmp_path / "audio.wav"
    media.write_bytes(b"audio")
    remote = RemoteAudioAnalysisPipeline(
        _endpoint(), FakeTransport(RemoteInferenceError("unavailable"))
    )
    deterministic = AudioAnalysisPipeline(
        vad=DeterministicVad(),
        asr=DeterministicAsr(),
        diarization=DeterministicDiarization(),
    )
    pipeline = FallbackAudioAnalysisPipeline(remote, deterministic)

    pipeline.analyze(media.resolve().as_uri(), 1, "zh-CN")

    assert pipeline.asr.model_release == "mock-asr-align@1"


def test_remote_factory_rejects_incomplete_configuration() -> None:
    with pytest.raises(ValueError, match="missing"):
        create_analysis_worker(Settings(analysis_adapter_mode="remote"))


def test_local_model_factory_is_lazy_and_preserves_release_provenance() -> None:
    worker = create_analysis_worker(
        Settings(
            analysis_adapter_mode="local_models",
            vad_release="silero-vad@sha256:vad",
            whisper_release="whisper-large-v3@sha256:asr",
            pyannote_release="community-1@sha256:diar",
        )
    )

    assert worker.pipeline.vad.model_release == "silero-vad@sha256:vad"
    assert worker.pipeline.asr.model_release == "whisper-large-v3@sha256:asr"
    assert worker.pipeline.diarization.model_release == "community-1@sha256:diar"


def test_stage_job_database_runtime_overrides_deterministic_default() -> None:
    job = StageJob(
        stage_run_id=uuid4(),
        stage_attempt_id=uuid4(),
        project_id=uuid4(),
        idempotency_key="runtime-selection",
        stage_type="ASR_ALIGN",
        output_prefix="file:///tmp/output",
        runtime_profile_id="gpu-audio",
        observed_control_version=1,
        params={
            "model_runtime": {
                "endpoint": "https://models.example.test/audio",
                "release": "audio-db@3",
                "license_id": "license-db-3",
                "approved_for_automation": True,
                "config": {},
            }
        },
        trace_id="runtime-selection-test",
    )

    worker = create_analysis_worker_for_job(job, Settings())

    assert worker.pipeline.asr.model_release == "audio-db@3:asr-align"


def test_registry_can_select_lazy_local_model_bundle() -> None:
    job = StageJob(
        stage_run_id=uuid4(),
        stage_attempt_id=uuid4(),
        project_id=uuid4(),
        idempotency_key="runtime-local-models",
        stage_type="ASR_ALIGN",
        output_prefix="file:///tmp/output",
        runtime_profile_id="modal-l4",
        observed_control_version=1,
        params={
            "model_runtime": {
                "release": "audio-bundle@7",
                "config": {
                    "adapter_mode": "local_models",
                    "vad_release": "silero@7",
                    "whisper_release": "whisper@7",
                    "pyannote_release": "pyannote@7",
                },
            }
        },
        trace_id="runtime-local-models-test",
    )

    worker = create_analysis_worker_for_job(job, Settings())

    assert worker.pipeline.vad.model_release == "silero@7"
    assert worker.pipeline.asr.model_release == "whisper@7"
    assert worker.pipeline.diarization.model_release == "pyannote@7"


def test_registry_can_select_lazy_qwen_vision_bundle() -> None:
    job = StageJob(
        stage_run_id=uuid4(),
        stage_attempt_id=uuid4(),
        project_id=uuid4(),
        idempotency_key="runtime-qwen-vision",
        stage_type="VISION_ANALYSIS",
        output_prefix="file:///tmp/output",
        runtime_profile_id="modal-l4",
        observed_control_version=1,
        params={
            "model_runtime": {
                "release": "qwen3-vl@approved-7",
                "config": {"adapter_mode": "qwen3_vl"},
            }
        },
        trace_id="runtime-qwen-vision-test",
    )

    worker = create_analysis_worker_for_job(job, Settings())

    assert worker.vision_pipeline.people.model_release == "qwen3-vl@approved-7:people"
    assert worker.vision_pipeline.scenes.model_release == "qwen3-vl@approved-7:scenes"
    assert worker.vision_pipeline.ocr.model_release == "qwen3-vl@approved-7:ocr"
    assert worker.vision_pipeline.geometry.model_release == "qwen3-vl@approved-7:geometry"
