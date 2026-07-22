from __future__ import annotations

import subprocess
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

from vtv_schemas.jobs import AssetRef, StageJob
from vtv_visual_worker.worker import VisualProductionWorker


def _run(args: list[str]) -> None:
    subprocess.run(args, check=True, capture_output=True)


def _tiny_video(path: Path, duration: float = 2.0, audio: bool = True) -> None:
    """Generate a tiny synthetic video with or without audio."""
    args = [
        "ffmpeg", "-loglevel", "error",
        "-f", "lavfi",
        "-i", f"color=c=blue:s=160x90:r=24:d={duration}",
    ]
    if audio:
        args += [
            "-f", "lavfi",
            "-i", f"sine=frequency=440:duration={duration}",
            "-shortest",
        ]
    args += [
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-y", str(path),
    ]
    _run(args)


def _sha(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _asset(path: Path, media_type: str = "video/mp4") -> AssetRef:
    return AssetRef(
        uri=path.resolve().as_uri(),
        sha256=_sha(path),
        media_type=media_type,
        size_bytes=path.stat().st_size,
    )


def _job(tmp_path: Path, inputs: list[AssetRef], params: dict) -> StageJob:
    return StageJob(
        stage_run_id=uuid4(),
        stage_attempt_id=uuid4(),
        project_id=uuid4(),
        episode_id=uuid4(),
        shot_id=uuid4(),
        idempotency_key="visual_qc:component_test",
        stage_type="VISUAL_QC",
        input_assets=inputs,
        output_prefix=(tmp_path / "visual_qc_out").resolve().as_uri(),
        runtime_profile_id="cpu-standard",
        observed_control_version=1,
        params=params,
        trace_id="component-visual-qc",
    )


def test_visual_qc_stage_with_real_video_passes(tmp_path: Path) -> None:
    """VISUAL_QC runs successfully on a real FFmpeg-synthesized video."""
    video = tmp_path / "candidate.mp4"
    _tiny_video(video, duration=2.0, audio=True)
    source = _asset(video)
    result = VisualProductionWorker().execute(
        _job(
            tmp_path,
            inputs=[source],
            params={
                "visual_qc_request": {
                    "evaluator_key": "visual_technical",
                    "route": "C",
                    "expected_duration_seconds": 2.0,
                    "hard_failure_below": {
                        "frame_integrity": 0.5,
                        "audio_stream_present": 0.5,
                    },
                    "thresholds": {
                        "frame_integrity": 0.8,
                        "duration_deviation": 0.9,
                        "resolution_match": 0.8,
                    },
                }
            },
        )
    )
    assert result.status == "OUTPUT_READY"
    payload = result.domain_artifacts[0].payload
    assert payload["has_hard_failure"] is False
    assert payload["metrics"]["frame_integrity"] == 1.0
    assert payload["metrics"]["audio_stream_present"] == 1.0
    assert payload["metrics"]["resolution_match"] == 1.0


def test_duration_deviation_passes_within_tolerance(tmp_path: Path) -> None:
    """duration_deviation metric PASS when actual duration within 8% of expected."""
    video = tmp_path / "candidate.mp4"
    _tiny_video(video, duration=2.0, audio=False)
    source = _asset(video)
    # Expected 2.0s, actual ~2.0s → deviation ~0% → score ~1.0 → PASS
    result = VisualProductionWorker().execute(
        _job(
            tmp_path,
            inputs=[source],
            params={
                "visual_qc_request": {
                    "expected_duration_seconds": 2.0,
                    "hard_failure_below": {},
                    "thresholds": {"duration_deviation": 0.9},
                }
            },
        )
    )
    payload = result.domain_artifacts[0].payload
    assert payload["metrics"]["duration_deviation"] >= 0.9
    assert payload["verdicts"]["duration_deviation"] == "PASS"


def test_duration_deviation_fails_with_large_mismatch(tmp_path: Path) -> None:
    """duration_deviation metric FAIL when actual duration exceeds 8% deviation."""
    video = tmp_path / "candidate.mp4"
    _tiny_video(video, duration=2.0, audio=False)
    source = _asset(video)
    # Expected 0.5s, actual ~2.0s → deviation ~300% → hard failure triggered
    result = VisualProductionWorker().execute(
        _job(
            tmp_path,
            inputs=[source],
            params={
                "visual_qc_request": {
                    "expected_duration_seconds": 0.5,
                    "hard_failure_below": {},
                    "thresholds": {"duration_deviation": 0.9},
                }
            },
        )
    )
    payload = result.domain_artifacts[0].payload
    # duration_deviation score should be very low
    assert payload["metrics"]["duration_deviation"] < 0.5
    assert payload["verdicts"]["duration_deviation"] == "FAIL"
    # Also triggers hard failure (>8% deviation)
    assert payload["has_hard_failure"] is True


def test_visual_qc_stage_no_output_assets(tmp_path: Path) -> None:
    """VISUAL_QC stage produces no output media assets — QC report only."""
    video = tmp_path / "candidate.mp4"
    _tiny_video(video, duration=1.0)
    source = _asset(video)
    result = VisualProductionWorker().execute(
        _job(
            tmp_path,
            inputs=[source],
            params={"visual_qc_request": {"expected_duration_seconds": 1.0}},
        )
    )
    assert result.status == "OUTPUT_READY"
    assert len(result.variants) == 1
    assert result.variants[0].output_assets == []


def test_visual_qc_domain_artifact_document_type(tmp_path: Path) -> None:
    """DomainArtifact document_type is VISUAL_QC_REPORT with full metrics payload."""
    video = tmp_path / "candidate.mp4"
    _tiny_video(video, duration=1.5, audio=True)
    source = _asset(video)
    result = VisualProductionWorker().execute(
        _job(
            tmp_path,
            inputs=[source],
            params={
                "visual_qc_request": {
                    "evaluator_key": "visual_technical",
                    "route": "D",
                    "expected_duration_seconds": 1.5,
                }
            },
        )
    )
    assert len(result.domain_artifacts) == 1
    artifact = result.domain_artifacts[0]
    assert artifact.document_type == "VISUAL_QC_REPORT"
    payload = artifact.payload
    # Full metrics dict present
    assert "metrics" in payload
    assert set(payload["metrics"].keys()) == {
        "frame_integrity",
        "duration_deviation",
        "resolution_match",
        "audio_stream_present",
    }
    assert "has_hard_failure" in payload
    assert "evaluator_key" in payload
    assert payload["evaluator_key"] == "visual_technical"
    assert payload["route"] == "D"
    # source_asset_sha256 links to the candidate video
    assert artifact.source_asset_sha256 == source.sha256
