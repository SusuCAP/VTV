from __future__ import annotations

import subprocess
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from vtv_media import probe_media

from .contracts import (
    SegmentationRequest,
    SegmentationResult,
    SubtitleCleanRequest,
    SubtitleCleanResult,
    VisualCandidate,
    VisualGenerationRequest,
)


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(4 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _ffmpeg(*args: str) -> None:
    subprocess.run(["ffmpeg", "-loglevel", "error", *args], check=True, capture_output=True)


@dataclass(frozen=True, slots=True)
class PassthroughSegmentationAdapter:
    """SAM3.1/MatAnyone2 contract stub — outputs source frame as alpha=1 mask."""

    model_release: str = "sam3.1-passthrough@1"

    def segment(
        self,
        request: SegmentationRequest,
        source_video: Path,
        output_dir: Path,
    ) -> SegmentationResult:
        probe_media(source_video)
        output_dir.mkdir(parents=True, exist_ok=True)

        if request.output_type == "mask_video":
            mask_path = output_dir / "mask.mp4"
            _ffmpeg(
                "-i", str(source_video),
                "-vf", "geq=r=255:g=255:b=255",
                "-c:v", "libx264", "-pix_fmt", "yuv420p",
                "-an", "-y", str(mask_path),
            )
        else:
            mask_path = output_dir / "mask.png"
            _ffmpeg(
                "-i", str(source_video),
                "-vframes", "1",
                "-vf", "geq=r=255:g=255:b=255",
                "-y", str(mask_path),
            )

        return SegmentationResult(
            shot_id=request.shot_id,
            mask_uri=mask_path.resolve().as_uri(),
            mask_sha256=_sha256_file(mask_path),
            mask_type=request.output_type,
            model_release=self.model_release,
        )


@dataclass(frozen=True, slots=True)
class PassthroughVisualGenerationAdapter:
    """Wan-Animate/MoCha contract stub — returns source unchanged."""

    model_release: str = "wan-animate-passthrough@1"
    route_handled: str = "C"  # VisualRoute value this adapter handles

    def generate(
        self,
        request: VisualGenerationRequest,
        source_video: Path,
        output_directory: Path,
        mask: Path | None = None,
    ) -> tuple[VisualCandidate, ...]:
        probe_media(source_video)
        output_directory.mkdir(parents=True, exist_ok=True)

        # Passthrough produces exactly one candidate (copy codec, no re-encode)
        variant_dir = output_directory / "variant_01"
        variant_dir.mkdir(parents=True, exist_ok=True)
        out_video = variant_dir / "output.mp4"
        _ffmpeg("-i", str(source_video), "-c", "copy", "-y", str(out_video))

        # Extract first frame as preview
        preview_path = output_directory / "preview.jpg"
        _ffmpeg(
            "-i", str(source_video),
            "-vframes", "1",
            "-f", "image2",
            "-y", str(preview_path),
        )

        probe = probe_media(out_video)
        return (
            VisualCandidate(
                shot_id=request.shot_id,
                variant_no=1,
                video_uri=out_video.resolve().as_uri(),
                video_sha256=_sha256_file(out_video),
                duration_seconds=probe.duration_seconds,
                model_release=self.model_release,
                seed=request.seed,
                route=request.route,
                preview_frame_uri=preview_path.resolve().as_uri(),
                preview_frame_sha256=_sha256_file(preview_path),
            ),
        )


@dataclass(frozen=True, slots=True)
class PassthroughSubtitleCleanAdapter:
    """Route B subtitle clean stub — returns source unchanged."""

    model_release: str = "subtitle-clean-passthrough@1"

    def clean(
        self,
        request: SubtitleCleanRequest,
        source_video: Path,
        output_dir: Path,
    ) -> SubtitleCleanResult:
        probe_media(source_video)
        output_dir.mkdir(parents=True, exist_ok=True)

        out_video = output_dir / "output.mp4"
        _ffmpeg("-i", str(source_video), "-c", "copy", "-y", str(out_video))

        return SubtitleCleanResult(
            shot_id=request.shot_id,
            video_uri=out_video.resolve().as_uri(),
            video_sha256=_sha256_file(out_video),
            model_release=self.model_release,
        )
