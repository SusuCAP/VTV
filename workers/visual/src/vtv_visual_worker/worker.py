from __future__ import annotations

import subprocess
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from vtv_production.contracts import (
    SegmentationAdapter,
    SegmentationRequest,
    SubtitleCleanRequest,
    VisualGenerationAdapter,
    VisualGenerationRequest,
)
from vtv_schemas.jobs import AssetRef, DomainArtifact, StageJob, StageResult, VariantResult


def _local_path(uri: str) -> Path:
    parsed = urlparse(uri)
    if parsed.scheme not in {"", "file"}:
        raise ValueError(f"visual worker requires a local file URI, got: {uri}")
    return Path(unquote(parsed.path if parsed.scheme else uri))


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(4 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _ffmpeg(*args: str) -> None:
    subprocess.run(["ffmpeg", "-loglevel", "error", *args], check=True, capture_output=True)


@dataclass(frozen=True, slots=True)
class VisualProductionWorker:
    segmentation: SegmentationAdapter | None = None
    character_replace: VisualGenerationAdapter | None = None
    background_replace: VisualGenerationAdapter | None = None
    full_regen: VisualGenerationAdapter | None = None
    subtitle_clean: Any | None = None  # SubtitleCleanAdapter

    def execute(self, job: StageJob) -> StageResult:
        stage = job.stage_type
        if stage == "VISUAL_CHARACTER_REPLACE":
            return self._character_replace(job)
        if stage == "VISUAL_BACKGROUND_REPLACE":
            return self._background_replace(job)
        if stage == "VISUAL_JOINT_REPLACE":
            return self._joint_replace(job)
        if stage == "VISUAL_FULL_REGEN":
            return self._full_regen(job)
        if stage == "VISUAL_SUBTITLE_CLEAN":
            return self._subtitle_clean(job)
        if stage == "VISUAL_KEYFRAME_PREVIEW":
            return self._keyframe_preview(job)
        raise ValueError(f"unsupported visual stage: {job.stage_type}")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _source_video_asset(self, job: StageJob) -> AssetRef:
        video_assets = [a for a in job.input_assets if a.media_type.startswith("video/")]
        if len(video_assets) != 1:
            raise ValueError(
                f"{job.stage_type} requires exactly one video input asset, "
                f"got {len(video_assets)}"
            )
        return video_assets[0]

    def _output_dir(self, job: StageJob) -> Path:
        path = _local_path(job.output_prefix)
        path.mkdir(parents=True, exist_ok=True)
        return path

    # ------------------------------------------------------------------
    # Stage handlers
    # ------------------------------------------------------------------

    def _character_replace(self, job: StageJob) -> StageResult:
        if self.character_replace is None:
            raise ValueError("VISUAL_CHARACTER_REPLACE requires a character_replace adapter")
        source_asset = self._source_video_asset(job)
        source_video = _local_path(source_asset.uri)
        output_dir = self._output_dir(job)
        request = VisualGenerationRequest.model_validate(job.params["visual_generation_request"])

        mask: Path | None = None
        if self.segmentation is not None:
            seg_request = SegmentationRequest(
                shot_id=request.shot_id,
                source_video_sha256=source_asset.sha256,
            )
            seg_result = self.segmentation.segment(seg_request, source_video, output_dir / "seg")
            mask = _local_path(seg_result.mask_uri)

        candidates = self.character_replace.generate(request, source_video, output_dir, mask)
        return self._build_result(job, candidates, source_asset.sha256, "VISUAL_CANDIDATES")

    def _background_replace(self, job: StageJob) -> StageResult:
        if self.background_replace is None:
            raise ValueError("VISUAL_BACKGROUND_REPLACE requires a background_replace adapter")
        source_asset = self._source_video_asset(job)
        source_video = _local_path(source_asset.uri)
        output_dir = self._output_dir(job)
        request = VisualGenerationRequest.model_validate(job.params["visual_generation_request"])

        mask: Path | None = None
        if self.segmentation is not None:
            seg_request = SegmentationRequest(
                shot_id=request.shot_id,
                source_video_sha256=source_asset.sha256,
            )
            seg_result = self.segmentation.segment(seg_request, source_video, output_dir / "seg")
            mask = _local_path(seg_result.mask_uri)

        candidates = self.background_replace.generate(request, source_video, output_dir, mask)
        return self._build_result(job, candidates, source_asset.sha256, "VISUAL_CANDIDATES")

    def _joint_replace(self, job: StageJob) -> StageResult:
        # Uses character_replace adapter as the primary visual operation.
        # Full implementations would run character + background passes independently.
        if self.character_replace is None:
            raise ValueError("VISUAL_JOINT_REPLACE requires a character_replace adapter")
        source_asset = self._source_video_asset(job)
        source_video = _local_path(source_asset.uri)
        output_dir = self._output_dir(job)
        request = VisualGenerationRequest.model_validate(job.params["visual_generation_request"])

        mask: Path | None = None
        if self.segmentation is not None:
            seg_request = SegmentationRequest(
                shot_id=request.shot_id,
                source_video_sha256=source_asset.sha256,
            )
            seg_result = self.segmentation.segment(seg_request, source_video, output_dir / "seg")
            mask = _local_path(seg_result.mask_uri)

        candidates = self.character_replace.generate(request, source_video, output_dir, mask)
        return self._build_result(job, candidates, source_asset.sha256, "VISUAL_CANDIDATES")

    def _full_regen(self, job: StageJob) -> StageResult:
        if self.full_regen is None:
            raise ValueError("VISUAL_FULL_REGEN requires a full_regen adapter")
        source_asset = self._source_video_asset(job)
        source_video = _local_path(source_asset.uri)
        output_dir = self._output_dir(job)
        request = VisualGenerationRequest.model_validate(job.params["visual_generation_request"])
        candidates = self.full_regen.generate(request, source_video, output_dir)
        return self._build_result(job, candidates, source_asset.sha256, "VISUAL_CANDIDATES")

    def _subtitle_clean(self, job: StageJob) -> StageResult:
        if self.subtitle_clean is None:
            raise ValueError("VISUAL_SUBTITLE_CLEAN requires a subtitle_clean adapter")
        source_asset = self._source_video_asset(job)
        source_video = _local_path(source_asset.uri)
        output_dir = self._output_dir(job)
        request = SubtitleCleanRequest.model_validate(job.params["subtitle_clean_request"])
        result = self.subtitle_clean.clean(request, source_video, output_dir)
        out_path = _local_path(result.video_uri)
        variant = VariantResult(
            variant_no=1,
            output_assets=[
                AssetRef(
                    uri=result.video_uri,
                    sha256=result.video_sha256,
                    media_type="video/mp4",
                    size_bytes=out_path.stat().st_size,
                    metadata={
                        "shot_id": str(result.shot_id),
                        "model_release": result.model_release,
                    },
                )
            ],
        )
        return StageResult(
            stage_run_id=job.stage_run_id,
            stage_attempt_id=job.stage_attempt_id,
            status="OUTPUT_READY",
            variants=[variant],
            domain_artifacts=[
                DomainArtifact(
                    document_type="VISUAL_CANDIDATES",
                    episode_id=job.episode_id,
                    source_asset_sha256=source_asset.sha256,
                    payload={
                        "shot_id": str(result.shot_id),
                        "route": "B",
                        "model_release": result.model_release,
                        "candidate_count": 1,
                    },
                )
            ],
            attempt_usage={"worker": "visual", "local": True},
        )

    def _keyframe_preview(self, job: StageJob) -> StageResult:
        source_asset = self._source_video_asset(job)
        source_video = _local_path(source_asset.uri)
        output_dir = self._output_dir(job)
        preview_path = output_dir / "preview.jpg"
        _ffmpeg(
            "-i", str(source_video),
            "-vframes", "1",
            "-f", "image2",
            "-y", str(preview_path),
        )
        preview_sha = _sha256_file(preview_path)
        variant = VariantResult(
            variant_no=1,
            output_assets=[
                AssetRef(
                    uri=preview_path.resolve().as_uri(),
                    sha256=preview_sha,
                    media_type="image/jpeg",
                    size_bytes=preview_path.stat().st_size,
                    metadata={"shot_id": str(job.shot_id) if job.shot_id else ""},
                )
            ],
        )
        return StageResult(
            stage_run_id=job.stage_run_id,
            stage_attempt_id=job.stage_attempt_id,
            status="OUTPUT_READY",
            variants=[variant],
            domain_artifacts=[
                DomainArtifact(
                    document_type="KEYFRAME_PREVIEW",
                    episode_id=job.episode_id,
                    source_asset_sha256=source_asset.sha256,
                    payload={
                        "preview_sha256": preview_sha,
                        "shot_id": str(job.shot_id) if job.shot_id else "",
                    },
                )
            ],
            attempt_usage={"worker": "visual", "local": True},
        )

    # ------------------------------------------------------------------
    # Result builder
    # ------------------------------------------------------------------

    def _build_result(
        self,
        job: StageJob,
        candidates: tuple,
        source_sha256: str,
        document_type: str,
    ) -> StageResult:
        variants: list[VariantResult] = []
        for candidate in candidates:
            out_path = _local_path(candidate.video_uri)
            assets = [
                AssetRef(
                    uri=candidate.video_uri,
                    sha256=candidate.video_sha256,
                    media_type="video/mp4",
                    size_bytes=out_path.stat().st_size,
                    metadata={
                        "shot_id": str(candidate.shot_id),
                        "route": candidate.route,
                        "model_release": candidate.model_release,
                    },
                )
            ]
            if candidate.preview_frame_uri is not None:
                preview_path = _local_path(candidate.preview_frame_uri)
                assets.append(
                    AssetRef(
                        uri=candidate.preview_frame_uri,
                        sha256=candidate.preview_frame_sha256 or "",
                        media_type="image/jpeg",
                        size_bytes=preview_path.stat().st_size,
                        metadata={"role": "preview_frame"},
                    )
                )
            variants.append(
                VariantResult(
                    variant_no=candidate.variant_no,
                    seed=candidate.seed,
                    output_assets=assets,
                    raw_metrics={
                        "duration_seconds": candidate.duration_seconds,
                        "route": candidate.route,
                    },
                )
            )
        first = candidates[0]
        return StageResult(
            stage_run_id=job.stage_run_id,
            stage_attempt_id=job.stage_attempt_id,
            status="OUTPUT_READY",
            variants=variants,
            domain_artifacts=[
                DomainArtifact(
                    document_type=document_type,
                    episode_id=job.episode_id,
                    source_asset_sha256=source_sha256,
                    payload={
                        "shot_id": str(first.shot_id),
                        "route": first.route,
                        "model_release": first.model_release,
                        "candidate_count": len(candidates),
                    },
                )
            ],
            attempt_usage={"worker": "visual", "local": True},
        )
