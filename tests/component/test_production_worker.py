import base64
import io
import subprocess
import wave
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

import pytest
from vtv_production import (
    LipSyncDecision,
    LipSyncLevel,
    LipSyncRequest,
    LocalizedUtterance,
    ReviewState,
    ShotDialogueFeatures,
    TtsRequest,
    Utterance,
    VoiceRelease,
    VoiceRightsSnapshot,
)
from vtv_production_worker import (
    LipSyncEndpoint,
    ProductionWorker,
    RawLipSyncCandidate,
    RawLipSyncResponse,
    RawTtsCandidate,
    RawTtsResponse,
    RemoteLipSyncAdapter,
    RemoteTtsAdapter,
    TtsAccessDeniedError,
    TtsEndpoint,
)
from vtv_schemas.jobs import AssetRef, StageJob


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


class FakeLipSyncTransport:
    def __init__(self, video: bytes) -> None:
        self.video = video
        self.payload = None

    def render(self, config: LipSyncEndpoint, payload: dict) -> RawLipSyncResponse:
        self.payload = payload
        return RawLipSyncResponse(
            candidates=tuple(
                RawLipSyncCandidate(
                    variant_no=index,
                    video_base64=base64.b64encode(self.video).decode(),
                    seed=100 + index,
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


def _video(path: Path, duration_seconds: float = 2) -> bytes:
    subprocess.run(
        [
            "ffmpeg",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"color=c=blue:s=64x64:d={duration_seconds}",
            "-pix_fmt",
            "yuv420p",
            "-y",
            str(path),
        ],
        check=True,
    )
    return path.read_bytes()


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


def _lipsync_request(source_hash: str, audio_hash: str) -> LipSyncRequest:
    shot_id = uuid4()
    rights = VoiceRightsSnapshot(
        rights_release_id=uuid4(),
        state_version=1,
        subject_id="character-1",
        allowed_operations=frozenset({"voice_clone", "lipsync"}),
        allowed_languages=frozenset({"en-US"}),
        allowed_markets=frozenset({"US"}),
        commercial_allowed=True,
        valid_at_execution=True,
    )
    features = ShotDialogueFeatures(
        shot_id=shot_id,
        mouth_visible=True,
        face_scale=0.3,
        occlusion=0.1,
        body_visible=False,
        dialogue_duration_seconds=2,
    )
    return LipSyncRequest(
        features=features,
        decision=LipSyncDecision(
            shot_id=shot_id,
            level=LipSyncLevel.L2_PRESERVE_SOURCE,
            reason_codes=("VISIBLE_CLOSE_DIALOGUE",),
            maximum_duration_deviation=0.04,
        ),
        source_video_sha256=source_hash,
        adopted_tts_variant_id=uuid4(),
        audio_sha256=audio_hash,
        target_language="en-US",
        target_market="US",
        rights=rights,
        seed=100,
        candidate_count=2,
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


def test_remote_lipsync_worker_emits_verified_multi_candidate_outputs(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.mp4"
    source_bytes = _video(source)
    audio = tmp_path / "audio.wav"
    audio.write_bytes(_wav())
    request = _lipsync_request(sha256(source_bytes).hexdigest(), sha256(_wav()).hexdigest())
    transport = FakeLipSyncTransport(source_bytes)
    adapter = RemoteLipSyncAdapter(
        LipSyncEndpoint(
            endpoint="https://lipsync.example.invalid/v1/render",
            model_release="latentsync@1.6",
            license_id="license-lipsync",
            approved_for_automation=True,
        ),
        transport,
    )
    worker = ProductionWorker(lipsync=adapter)
    job = StageJob(
        stage_run_id=uuid4(),
        stage_attempt_id=uuid4(),
        project_id=uuid4(),
        episode_id=uuid4(),
        shot_id=request.features.shot_id,
        idempotency_key="lipsync:shot-1",
        stage_type="LIPSYNC_GENERATE",
        input_assets=[
            AssetRef(
                uri=source.resolve().as_uri(),
                sha256=request.source_video_sha256,
                media_type="video/mp4",
                size_bytes=source.stat().st_size,
            ),
            AssetRef(
                uri=audio.resolve().as_uri(),
                sha256=request.audio_sha256,
                media_type="audio/wav",
                size_bytes=audio.stat().st_size,
            ),
        ],
        output_prefix=(tmp_path / "outputs").resolve().as_uri(),
        runtime_profile_id="gpu-render",
        observed_control_version=1,
        params={
            "lipsync_request": request.model_dump(mode="json"),
            "router_release": "tiered-lipsync-router@1",
        },
        trace_id="lipsync-component-test",
    )

    result = worker.execute(job)

    assert result.status == "OUTPUT_READY"
    assert len(result.variants) == 2
    assert all(
        item.raw_metrics["lipsync_level"] == "L2_PRESERVE_SOURCE"
        for item in result.variants
    )
    assert result.domain_artifacts[0].payload["rights_state_version"] == 1
    assert transport.payload["level"] == "L2_PRESERVE_SOURCE"
