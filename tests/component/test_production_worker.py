import base64
import io
import wave
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

import pytest
from vtv_production import (
    LocalizedUtterance,
    ReviewState,
    TtsRequest,
    Utterance,
    VoiceRelease,
    VoiceRightsSnapshot,
)
from vtv_production_worker import (
    ProductionWorker,
    RawTtsCandidate,
    RawTtsResponse,
    RemoteTtsAdapter,
    TtsAccessDeniedError,
    TtsEndpoint,
)
from vtv_schemas.jobs import StageJob


class FakeTransport:
    def __init__(self, audio: bytes, *, duration_seed: int = 42) -> None:
        self.audio = audio
        self.duration_seed = duration_seed
        self.payload = None

    def synthesize(self, config: TtsEndpoint, payload: dict) -> RawTtsResponse:
        self.payload = payload
        return RawTtsResponse(
            candidates=tuple(
                RawTtsCandidate(
                    variant_no=index,
                    audio_base64=base64.b64encode(self.audio).decode(),
                    seed=self.duration_seed + index - 1,
                )
                for index in range(1, payload["candidate_count"] + 1)
            )
        )


def _wav(duration_seconds: float = 2) -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(16000)
        handle.writeframes(b"\0\0" * int(16000 * duration_seconds))
    return output.getvalue()


def _request() -> TtsRequest:
    character_id = "character-1"
    utterance = Utterance(
        utterance_id="utterance-1",
        character_id=character_id,
        source_text="你好",
        source_language="zh-CN",
        start_seconds=0,
        end_seconds=2,
        emotion="warm",
    )
    localized = LocalizedUtterance(
        utterance=utterance,
        target_text="Hello",
        target_language="en-US",
        target_market="US",
        localization_release="localization@1",
        review_state=ReviewState.HUMAN_APPROVED,
    )
    rights = VoiceRightsSnapshot(
        rights_release_id=uuid4(),
        state_version=1,
        subject_id=character_id,
        allowed_operations=frozenset({"voice_clone"}),
        allowed_languages=frozenset({"en-US"}),
        allowed_markets=frozenset({"US"}),
        commercial_allowed=True,
        valid_at_execution=True,
    )
    voice = VoiceRelease(
        voice_release_id=uuid4(),
        character_id=character_id,
        model_release="voxcpm2@candidate-1",
        reference_asset_sha256s=(sha256(b"voice-reference").hexdigest(),),
        rights=rights,
    )
    return TtsRequest(
        localized=localized,
        voice_release=voice,
        seed=42,
        candidate_count=2,
    )


def _job(tmp_path: Path, request: TtsRequest) -> StageJob:
    return StageJob(
        stage_run_id=uuid4(),
        stage_attempt_id=uuid4(),
        project_id=uuid4(),
        episode_id=uuid4(),
        idempotency_key="tts:utterance-1",
        stage_type="TTS_GENERATE",
        output_prefix=tmp_path.resolve().as_uri(),
        runtime_profile_id="gpu-audio",
        observed_control_version=1,
        params={
            "tts_request": request.model_dump(mode="json"),
            "maximum_duration_deviation": 0.04,
        },
        trace_id="tts-component-test",
    )


def test_remote_tts_worker_emits_verified_multi_candidate_outputs(tmp_path: Path) -> None:
    transport = FakeTransport(_wav())
    endpoint = TtsEndpoint(
        endpoint="https://tts.example.invalid/v1/synthesize",
        model_release="voxcpm2@candidate-1",
        license_id="license-1",
        approved_for_automation=True,
    )
    worker = ProductionWorker(RemoteTtsAdapter(endpoint, transport))

    result = worker.execute(_job(tmp_path, _request()))

    assert result.status == "OUTPUT_READY"
    assert len(result.variants) == 2
    assert [item.seed for item in result.variants] == [42, 43]
    assert all(item.raw_metrics["duration_deviation"] == 0 for item in result.variants)
    assert result.domain_artifacts[0].payload["candidate_count"] == 2
    assert transport.payload["target_duration_seconds"] == 2
    for variant in result.variants:
        asset = variant.output_assets[0]
        assert Path(asset.uri.removeprefix("file://")).read_bytes() == _wav()


def test_remote_tts_rejects_unapproved_release_before_transport(tmp_path: Path) -> None:
    adapter = RemoteTtsAdapter(
        TtsEndpoint(
            endpoint="https://tts.example.invalid/v1/synthesize",
            model_release="voxcpm2@unapproved",
            license_id="license-1",
            approved_for_automation=False,
        ),
        FakeTransport(_wav()),
    )

    with pytest.raises(TtsAccessDeniedError, match="not approved"):
        adapter.synthesize(_request(), tmp_path)


def test_worker_rejects_candidate_outside_route_duration_tolerance(tmp_path: Path) -> None:
    endpoint = TtsEndpoint(
        endpoint="https://tts.example.invalid/v1/synthesize",
        model_release="voxcpm2@candidate-1",
        license_id="license-1",
        approved_for_automation=True,
    )
    worker = ProductionWorker(RemoteTtsAdapter(endpoint, FakeTransport(_wav(2.2))))

    with pytest.raises(ValueError, match="duration exceeds"):
        worker.execute(_job(tmp_path, _request()))
