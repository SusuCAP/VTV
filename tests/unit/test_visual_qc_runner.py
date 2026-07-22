from __future__ import annotations

from uuid import uuid4

import pytest
from vtv_schemas.jobs import AssetRef, StageJob

_GOOD_SHA = "a" * 64
_GOOD_SHA2 = "b" * 64


def _job(
    tmp_path,
    inputs: list[AssetRef],
    params: dict | None = None,
) -> StageJob:
    return StageJob(
        stage_run_id=uuid4(),
        stage_attempt_id=uuid4(),
        project_id=uuid4(),
        episode_id=uuid4(),
        shot_id=uuid4(),
        idempotency_key="visual_qc:test",
        stage_type="VISUAL_QC",
        input_assets=inputs,
        output_prefix=(tmp_path / "visual_qc").resolve().as_uri(),
        runtime_profile_id="cpu-standard",
        observed_control_version=1,
        params=params or {},
        trace_id="test-visual-qc",
    )


def _video_asset(sha: str = _GOOD_SHA) -> AssetRef:
    return AssetRef(
        uri=f"file:///tmp/fake_{sha[:8]}.mp4",
        sha256=sha,
        media_type="video/mp4",
        size_bytes=1024,
    )


def _make_worker():
    from vtv_visual_worker.worker import VisualProductionWorker
    return VisualProductionWorker()


# ── visual_qc_request validation ──────────────────────────────────────────────

def test_visual_qc_request_no_params_raises_without_video(tmp_path) -> None:
    """VISUAL_QC with no video input assets raises ValueError."""
    worker = _make_worker()
    job = _job(tmp_path, inputs=[], params={})
    with pytest.raises(ValueError, match="VISUAL_QC requires at least one video input asset"):
        worker._visual_qc(job)


def test_visual_qc_request_evaluator_key_defaults(tmp_path) -> None:
    """evaluator_key defaults to 'visual_technical' when not specified in params."""
    from vtv_visual_worker.worker import VisualProductionWorker

    worker = VisualProductionWorker()
    # Patch probe_media to return a controlled result
    import vtv_visual_worker.worker as worker_module

    class FakeStream:
        codec_type = "video"
        frame_rate = 24.0
        width = 1920
        height = 1080

    class FakeAudioStream:
        codec_type = "audio"

    class FakeProbe:
        duration_seconds = 2.0
        @property
        def video_streams(self):
            return [FakeStream()]
        @property
        def audio_streams(self):
            return [FakeAudioStream()]

    original_probe = worker_module.probe_media

    def mock_probe(path, **kwargs):
        return FakeProbe()

    worker_module.probe_media = mock_probe
    try:
        asset = _video_asset()
        job = _job(
            tmp_path,
            inputs=[asset],
            params={"visual_qc_request": {}},  # no evaluator_key
        )
        result = worker._visual_qc(job)
        payload = result.domain_artifacts[0].payload
        assert payload["evaluator_key"] == "visual_technical"
    finally:
        worker_module.probe_media = original_probe


# ── frame_integrity metric calculation ────────────────────────────────────────

def test_frame_integrity_positive_when_frame_rate_and_duration(tmp_path) -> None:
    """frame_integrity=1.0 when video stream has positive frame_rate and duration."""
    import vtv_visual_worker.worker as worker_module

    class FakeVideoStream:
        codec_type = "video"
        frame_rate = 25.0
        width = 1280
        height = 720

    class FakeProbe:
        duration_seconds = 2.0
        @property
        def video_streams(self):
            return [FakeVideoStream()]
        @property
        def audio_streams(self):
            return []

    original = worker_module.probe_media
    worker_module.probe_media = lambda p, **kw: FakeProbe()
    try:
        result = _make_worker()._visual_qc(
            _job(tmp_path, inputs=[_video_asset()],
                 params={"visual_qc_request": {"expected_duration_seconds": 2.0}})
        )
        assert result.domain_artifacts[0].payload["metrics"]["frame_integrity"] == 1.0
    finally:
        worker_module.probe_media = original


def test_frame_integrity_zero_when_no_frame_rate(tmp_path) -> None:
    """frame_integrity=0.0 when video stream has no frame_rate (nb_frames=0)."""
    import vtv_visual_worker.worker as worker_module

    class FakeVideoStream:
        codec_type = "video"
        frame_rate = None
        width = 1280
        height = 720

    class FakeProbe:
        duration_seconds = 2.0
        @property
        def video_streams(self):
            return [FakeVideoStream()]
        @property
        def audio_streams(self):
            return []

    original = worker_module.probe_media
    worker_module.probe_media = lambda p, **kw: FakeProbe()
    try:
        result = _make_worker()._visual_qc(
            _job(tmp_path, inputs=[_video_asset()],
                 params={"visual_qc_request": {}})
        )
        assert result.domain_artifacts[0].payload["metrics"]["frame_integrity"] == 0.0
    finally:
        worker_module.probe_media = original


# ── duration_deviation metric calculation ─────────────────────────────────────

def test_duration_deviation_perfect_match(tmp_path) -> None:
    """duration_deviation=1.0 when actual equals expected."""
    import vtv_visual_worker.worker as worker_module

    class FakeVideoStream:
        codec_type = "video"
        frame_rate = 24.0
        width = 1920
        height = 1080

    class FakeProbe:
        duration_seconds = 3.0
        @property
        def video_streams(self):
            return [FakeVideoStream()]
        @property
        def audio_streams(self):
            return []

    original = worker_module.probe_media
    worker_module.probe_media = lambda p, **kw: FakeProbe()
    try:
        result = _make_worker()._visual_qc(
            _job(tmp_path, inputs=[_video_asset()],
                 params={"visual_qc_request": {"expected_duration_seconds": 3.0}})
        )
        assert result.domain_artifacts[0].payload["metrics"]["duration_deviation"] == 1.0
    finally:
        worker_module.probe_media = original


def test_duration_deviation_partial_mismatch(tmp_path) -> None:
    """duration_deviation = 1 - deviation_ratio when within tolerance."""
    import vtv_visual_worker.worker as worker_module

    class FakeVideoStream:
        codec_type = "video"
        frame_rate = 24.0
        width = 1920
        height = 1080

    class FakeProbe:
        duration_seconds = 1.1  # 10% deviation from expected 1.0
        @property
        def video_streams(self):
            return [FakeVideoStream()]
        @property
        def audio_streams(self):
            return []

    original = worker_module.probe_media
    worker_module.probe_media = lambda p, **kw: FakeProbe()
    try:
        result = _make_worker()._visual_qc(
            _job(tmp_path, inputs=[_video_asset()],
                 params={"visual_qc_request": {"expected_duration_seconds": 1.0}})
        )
        score = result.domain_artifacts[0].payload["metrics"]["duration_deviation"]
        assert abs(score - 0.9) < 1e-9
    finally:
        worker_module.probe_media = original


# ── resolution_match metric calculation ───────────────────────────────────────

def test_resolution_match_positive_with_dimensions(tmp_path) -> None:
    """resolution_match=1.0 when video stream has positive width and height."""
    import vtv_visual_worker.worker as worker_module

    class FakeVideoStream:
        codec_type = "video"
        frame_rate = 24.0
        width = 1920
        height = 1080

    class FakeProbe:
        duration_seconds = 1.0
        @property
        def video_streams(self):
            return [FakeVideoStream()]
        @property
        def audio_streams(self):
            return []

    original = worker_module.probe_media
    worker_module.probe_media = lambda p, **kw: FakeProbe()
    try:
        result = _make_worker()._visual_qc(
            _job(tmp_path, inputs=[_video_asset()], params={"visual_qc_request": {}})
        )
        assert result.domain_artifacts[0].payload["metrics"]["resolution_match"] == 1.0
    finally:
        worker_module.probe_media = original


# ── audio_stream_present metric calculation ───────────────────────────────────

def test_audio_stream_present_when_audio_exists(tmp_path) -> None:
    """audio_stream_present=1.0 when audio stream is detected."""
    import vtv_visual_worker.worker as worker_module

    class FakeVideoStream:
        codec_type = "video"
        frame_rate = 24.0
        width = 1280
        height = 720

    class FakeAudioStream:
        codec_type = "audio"

    class FakeProbe:
        duration_seconds = 2.0
        @property
        def video_streams(self):
            return [FakeVideoStream()]
        @property
        def audio_streams(self):
            return [FakeAudioStream()]

    original = worker_module.probe_media
    worker_module.probe_media = lambda p, **kw: FakeProbe()
    try:
        result = _make_worker()._visual_qc(
            _job(tmp_path, inputs=[_video_asset()], params={"visual_qc_request": {}})
        )
        assert result.domain_artifacts[0].payload["metrics"]["audio_stream_present"] == 1.0
    finally:
        worker_module.probe_media = original


def test_audio_stream_absent_when_no_audio(tmp_path) -> None:
    """audio_stream_present=0.0 when no audio stream."""
    import vtv_visual_worker.worker as worker_module

    class FakeVideoStream:
        codec_type = "video"
        frame_rate = 24.0
        width = 1280
        height = 720

    class FakeProbe:
        duration_seconds = 2.0
        @property
        def video_streams(self):
            return [FakeVideoStream()]
        @property
        def audio_streams(self):
            return []

    original = worker_module.probe_media
    worker_module.probe_media = lambda p, **kw: FakeProbe()
    try:
        result = _make_worker()._visual_qc(
            _job(tmp_path, inputs=[_video_asset()], params={"visual_qc_request": {}})
        )
        assert result.domain_artifacts[0].payload["metrics"]["audio_stream_present"] == 0.0
    finally:
        worker_module.probe_media = original


# ── hard_failure detection ─────────────────────────────────────────────────────

def test_hard_failure_triggers_when_frame_integrity_below_threshold(tmp_path) -> None:
    """has_hard_failure=True when frame_integrity score < hard_failure_below."""
    import vtv_visual_worker.worker as worker_module

    class FakeVideoStream:
        codec_type = "video"
        frame_rate = None  # no frames -> frame_integrity=0.0
        width = 1280
        height = 720

    class FakeProbe:
        duration_seconds = 1.0
        @property
        def video_streams(self):
            return [FakeVideoStream()]
        @property
        def audio_streams(self):
            return []

    original = worker_module.probe_media
    worker_module.probe_media = lambda p, **kw: FakeProbe()
    try:
        result = _make_worker()._visual_qc(
            _job(
                tmp_path,
                inputs=[_video_asset()],
                params={
                    "visual_qc_request": {
                        "hard_failure_below": {"frame_integrity": 0.5},
                    }
                },
            )
        )
        assert result.domain_artifacts[0].payload["has_hard_failure"] is True
    finally:
        worker_module.probe_media = original


def test_no_hard_failure_when_all_metrics_above_threshold(tmp_path) -> None:
    """has_hard_failure=False when all metrics meet hard_failure_below thresholds."""
    import vtv_visual_worker.worker as worker_module

    class FakeVideoStream:
        codec_type = "video"
        frame_rate = 24.0
        width = 1280
        height = 720

    class FakeAudioStream:
        codec_type = "audio"

    class FakeProbe:
        duration_seconds = 2.0
        @property
        def video_streams(self):
            return [FakeVideoStream()]
        @property
        def audio_streams(self):
            return [FakeAudioStream()]

    original = worker_module.probe_media
    worker_module.probe_media = lambda p, **kw: FakeProbe()
    try:
        result = _make_worker()._visual_qc(
            _job(
                tmp_path,
                inputs=[_video_asset()],
                params={
                    "visual_qc_request": {
                        "expected_duration_seconds": 2.0,
                        "hard_failure_below": {
                            "frame_integrity": 0.5,
                            "audio_stream_present": 0.5,
                        },
                    }
                },
            )
        )
        assert result.domain_artifacts[0].payload["has_hard_failure"] is False
    finally:
        worker_module.probe_media = original


# ── domain artifact output structure ──────────────────────────────────────────

def test_domain_artifact_document_type_is_visual_qc_report(tmp_path) -> None:
    """DomainArtifact document_type must be VISUAL_QC_REPORT."""
    import vtv_visual_worker.worker as worker_module

    class FakeVideoStream:
        codec_type = "video"
        frame_rate = 24.0
        width = 1920
        height = 1080

    class FakeProbe:
        duration_seconds = 1.5
        @property
        def video_streams(self):
            return [FakeVideoStream()]
        @property
        def audio_streams(self):
            return []

    original = worker_module.probe_media
    worker_module.probe_media = lambda p, **kw: FakeProbe()
    try:
        result = _make_worker()._visual_qc(
            _job(tmp_path, inputs=[_video_asset()], params={"visual_qc_request": {}})
        )
        assert len(result.domain_artifacts) == 1
        assert result.domain_artifacts[0].document_type == "VISUAL_QC_REPORT"
        assert result.variants[0].output_assets == []
        assert result.status == "OUTPUT_READY"
    finally:
        worker_module.probe_media = original
