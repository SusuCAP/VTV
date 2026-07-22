from __future__ import annotations

import subprocess
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

from vtv_media import probe_media
from vtv_production.contracts import SegmentationRequest, VisualGenerationRequest
from vtv_production.visual_adapters import (
    PassthroughSegmentationAdapter,
    PassthroughSubtitleCleanAdapter,
    PassthroughVisualGenerationAdapter,
)
from vtv_schemas.jobs import AssetRef, StageJob
from vtv_visual_worker.worker import VisualProductionWorker

_GOOD_SHA = "a" * 64


def _run(args: list[str]) -> None:
    subprocess.run(args, check=True, capture_output=True)


def _tiny_video(path: Path, duration: float = 1.0, color: str = "black") -> None:
    _run(
        [
            "ffmpeg", "-loglevel", "error",
            "-f", "lavfi",
            "-i", f"color=c={color}:s=160x90:r=24:d={duration}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-y", str(path),
        ]
    )


def _sha(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _asset(path: Path, media_type: str = "video/mp4") -> AssetRef:
    return AssetRef(
        uri=path.resolve().as_uri(),
        sha256=_sha(path),
        media_type=media_type,
        size_bytes=path.stat().st_size,
    )


def _job(
    tmp_path: Path,
    stage_type: str,
    *,
    inputs: tuple = (),
    params: dict | None = None,
    shot_id=None,
) -> StageJob:
    return StageJob(
        stage_run_id=uuid4(),
        stage_attempt_id=uuid4(),
        project_id=uuid4(),
        episode_id=uuid4(),
        shot_id=shot_id or uuid4(),
        idempotency_key=f"visual:{stage_type.lower()}",
        stage_type=stage_type,
        input_assets=list(inputs),
        output_prefix=(tmp_path / stage_type.lower()).resolve().as_uri(),
        runtime_profile_id="cpu-visual",
        observed_control_version=1,
        params=params or {},
        trace_id=f"test-{stage_type.lower()}",
    )


def _visual_request(shot_id, sha: str, route: str = "C") -> dict:
    return {
        "shot_id": str(shot_id),
        "route": route,
        "source_video_sha256": sha,
        "source_video_duration_seconds": 1.0,
        "seed": 0,
        "candidate_count": 1,
    }


# ── PassthroughSegmentationAdapter ────────────────────────────────────────────


def test_passthrough_segmentation_returns_valid_result(tmp_path: Path) -> None:
    video = tmp_path / "source.mp4"
    _tiny_video(video)
    adapter = PassthroughSegmentationAdapter()
    req = SegmentationRequest(shot_id=uuid4(), source_video_sha256=_sha(video))
    result = adapter.segment(req, video, tmp_path / "seg_out")
    assert result.shot_id == req.shot_id
    assert result.mask_type == "alpha_matte"
    assert result.model_release == "sam3.1-passthrough@1"
    assert len(result.mask_sha256) == 64


def test_passthrough_segmentation_mask_file_exists(tmp_path: Path) -> None:
    video = tmp_path / "source.mp4"
    _tiny_video(video)
    adapter = PassthroughSegmentationAdapter()
    req = SegmentationRequest(shot_id=uuid4(), source_video_sha256=_sha(video))
    result = adapter.segment(req, video, tmp_path / "seg_out")
    mask_path = Path(result.mask_uri.removeprefix("file://"))
    assert mask_path.exists()
    assert mask_path.suffix == ".png"


# ── PassthroughVisualGenerationAdapter ────────────────────────────────────────


def test_passthrough_visual_generation_returns_candidate_tuple(tmp_path: Path) -> None:
    video = tmp_path / "source.mp4"
    _tiny_video(video)
    adapter = PassthroughVisualGenerationAdapter(route_handled="C")
    shot_id = uuid4()
    req = VisualGenerationRequest(
        shot_id=shot_id,
        route="C",
        source_video_sha256=_sha(video),
        source_video_duration_seconds=1.0,
        seed=7,
    )
    candidates = adapter.generate(req, video, tmp_path / "gen_out")
    assert len(candidates) == 1
    assert candidates[0].shot_id == shot_id
    assert candidates[0].variant_no == 1
    assert candidates[0].route == "C"
    assert candidates[0].seed == 7


def test_passthrough_visual_generation_output_video_probes_ok(tmp_path: Path) -> None:
    video = tmp_path / "source.mp4"
    _tiny_video(video)
    adapter = PassthroughVisualGenerationAdapter()
    req = VisualGenerationRequest(
        shot_id=uuid4(),
        route="C",
        source_video_sha256=_sha(video),
        source_video_duration_seconds=1.0,
        seed=0,
    )
    candidates = adapter.generate(req, video, tmp_path / "gen_out")
    out_path = Path(candidates[0].video_uri.removeprefix("file://"))
    assert out_path.exists()
    probe = probe_media(out_path)
    assert probe.duration_seconds > 0


def test_passthrough_visual_generation_preview_frame_exists(tmp_path: Path) -> None:
    video = tmp_path / "source.mp4"
    _tiny_video(video)
    adapter = PassthroughVisualGenerationAdapter()
    req = VisualGenerationRequest(
        shot_id=uuid4(),
        route="C",
        source_video_sha256=_sha(video),
        source_video_duration_seconds=1.0,
        seed=0,
    )
    candidates = adapter.generate(req, video, tmp_path / "gen_out")
    assert candidates[0].preview_frame_uri is not None
    preview_path = Path(candidates[0].preview_frame_uri.removeprefix("file://"))
    assert preview_path.exists()
    assert preview_path.suffix == ".jpg"


# ── VisualProductionWorker — stage handlers ────────────────────────────────────


def _make_worker() -> VisualProductionWorker:
    return VisualProductionWorker(
        segmentation=PassthroughSegmentationAdapter(),
        character_replace=PassthroughVisualGenerationAdapter(route_handled="C"),
        background_replace=PassthroughVisualGenerationAdapter(route_handled="D"),
        full_regen=PassthroughVisualGenerationAdapter(route_handled="F"),
        subtitle_clean=PassthroughSubtitleCleanAdapter(),
    )


def test_worker_character_replace(tmp_path: Path) -> None:
    video = tmp_path / "source.mp4"
    _tiny_video(video)
    source = _asset(video)
    shot_id = uuid4()
    result = _make_worker().execute(
        _job(
            tmp_path,
            "VISUAL_CHARACTER_REPLACE",
            inputs=(source,),
            params={"visual_generation_request": _visual_request(shot_id, source.sha256, "C")},
            shot_id=shot_id,
        )
    )
    assert result.status == "OUTPUT_READY"
    assert len(result.variants) == 1
    assert result.domain_artifacts[0].document_type == "VISUAL_CANDIDATES"


def test_worker_background_replace(tmp_path: Path) -> None:
    video = tmp_path / "source.mp4"
    _tiny_video(video)
    source = _asset(video)
    shot_id = uuid4()
    result = _make_worker().execute(
        _job(
            tmp_path,
            "VISUAL_BACKGROUND_REPLACE",
            inputs=(source,),
            params={"visual_generation_request": _visual_request(shot_id, source.sha256, "D")},
            shot_id=shot_id,
        )
    )
    assert result.status == "OUTPUT_READY"
    assert result.domain_artifacts[0].document_type == "VISUAL_CANDIDATES"


def test_worker_subtitle_clean(tmp_path: Path) -> None:
    video = tmp_path / "source.mp4"
    _tiny_video(video)
    source = _asset(video)
    shot_id = uuid4()
    result = _make_worker().execute(
        _job(
            tmp_path,
            "VISUAL_SUBTITLE_CLEAN",
            inputs=(source,),
            params={
                "subtitle_clean_request": {
                    "shot_id": str(shot_id),
                    "source_video_sha256": source.sha256,
                }
            },
            shot_id=shot_id,
        )
    )
    assert result.status == "OUTPUT_READY"
    assert result.domain_artifacts[0].document_type == "VISUAL_CANDIDATES"


def test_worker_full_regen(tmp_path: Path) -> None:
    video = tmp_path / "source.mp4"
    _tiny_video(video)
    source = _asset(video)
    shot_id = uuid4()
    result = _make_worker().execute(
        _job(
            tmp_path,
            "VISUAL_FULL_REGEN",
            inputs=(source,),
            params={"visual_generation_request": _visual_request(shot_id, source.sha256, "F")},
            shot_id=shot_id,
        )
    )
    assert result.status == "OUTPUT_READY"
    assert result.domain_artifacts[0].document_type == "VISUAL_CANDIDATES"


def test_worker_keyframe_preview(tmp_path: Path) -> None:
    video = tmp_path / "source.mp4"
    _tiny_video(video)
    source = _asset(video)
    shot_id = uuid4()
    result = _make_worker().execute(
        _job(
            tmp_path,
            "VISUAL_KEYFRAME_PREVIEW",
            inputs=(source,),
            shot_id=shot_id,
        )
    )
    assert result.status == "OUTPUT_READY"
    assert result.domain_artifacts[0].document_type == "KEYFRAME_PREVIEW"
    preview_asset = result.variants[0].output_assets[0]
    assert preview_asset.media_type == "image/jpeg"
    preview_path = Path(preview_asset.uri.removeprefix("file://"))
    assert preview_path.exists()
    assert preview_path.suffix == ".jpg"
