from pathlib import Path

import pytest
from vtv_analysis import (
    AudioAnalysisPipeline,
    DeterministicAsr,
    DeterministicDiarization,
    DeterministicVad,
)
from vtv_analysis_worker.config import Settings
from vtv_analysis_worker.factory import create_analysis_worker
from vtv_analysis_worker.runtime import (
    FallbackAudioAnalysisPipeline,
    ModelAccessDeniedError,
    ModelEndpoint,
    RemoteAudioAnalysisPipeline,
    RemoteInferenceError,
)


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
