from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlparse

from vtv_production import LipSyncAdapter, LipSyncRequest, TtsAdapter, TtsRequest
from vtv_schemas.jobs import AssetRef, DomainArtifact, StageJob, StageResult, VariantResult


@dataclass(frozen=True, slots=True)
class ProductionWorker:
    tts: TtsAdapter | None = None
    lipsync: LipSyncAdapter | None = None

    def execute(self, job: StageJob) -> StageResult:
        if job.stage_type == "TTS_GENERATE":
            return self._execute_tts(job)
        if job.stage_type == "LIPSYNC_GENERATE":
            return self._execute_lipsync(job)
        raise ValueError(f"unsupported production stage: {job.stage_type}")

    def _execute_tts(self, job: StageJob) -> StageResult:
        if self.tts is None:
            raise ValueError("TTS_GENERATE requires a TTS adapter")
        if job.input_assets:
            raise ValueError("TTS_GENERATE consumes its immutable request from Stage params")
        try:
            request = TtsRequest.model_validate(job.params["tts_request"])
        except (KeyError, ValueError) as exc:
            raise ValueError("TTS_GENERATE requires a valid tts_request") from exc
        output_directory = _local_path(job.output_prefix) / request.localized.utterance.utterance_id
        candidates = self.tts.synthesize(request, output_directory)
        maximum_deviation = float(job.params.get("maximum_duration_deviation", 0.08))
        if maximum_deviation <= 0 or maximum_deviation > 0.08:
            raise ValueError("maximum duration deviation must be within (0, 0.08]")
        variants: list[VariantResult] = []
        for candidate in candidates:
            deviation = abs(candidate.duration_seconds - request.target_duration_seconds)
            deviation /= request.target_duration_seconds
            if deviation > maximum_deviation:
                raise ValueError("TTS candidate duration exceeds shot route tolerance")
            path = _local_path(candidate.audio_uri)
            asset = AssetRef(
                uri=candidate.audio_uri,
                sha256=candidate.audio_sha256,
                media_type="audio/wav",
                size_bytes=path.stat().st_size,
                metadata={
                    "utterance_id": candidate.utterance_id,
                    "voice_release_id": str(candidate.voice_release_id),
                    "model_release": candidate.model_release,
                },
            )
            variants.append(
                VariantResult(
                    variant_no=candidate.variant_no,
                    seed=candidate.seed,
                    output_assets=[asset],
                    raw_metrics={
                        "duration_seconds": candidate.duration_seconds,
                        "duration_deviation": deviation,
                        "speed": candidate.speed,
                        "emotion": candidate.emotion,
                    },
                )
            )
        return StageResult(
            stage_run_id=job.stage_run_id,
            stage_attempt_id=job.stage_attempt_id,
            status="OUTPUT_READY",
            variants=variants,
            domain_artifacts=[
                DomainArtifact(
                    document_type="TTS_CANDIDATES",
                    episode_id=job.episode_id,
                    source_asset_sha256=request.voice_release.reference_asset_sha256s[0],
                    payload={
                        "utterance_id": request.localized.utterance.utterance_id,
                        "localization_release": request.localized.localization_release,
                        "voice_release_id": str(request.voice_release.voice_release_id),
                        "rights_release_id": str(
                            request.voice_release.rights.rights_release_id
                        ),
                        "rights_state_version": request.voice_release.rights.state_version,
                        "model_release": self.tts.model_release,
                        "candidate_count": len(candidates),
                        "target_duration_seconds": request.target_duration_seconds,
                    },
                )
            ],
            attempt_usage={"worker": "production", "local": True},
        )

    def _execute_lipsync(self, job: StageJob) -> StageResult:
        if self.lipsync is None:
            raise ValueError("LIPSYNC_GENERATE requires a lipsync adapter")
        if len(job.input_assets) != 2:
            raise ValueError("LIPSYNC_GENERATE requires source video and adopted TTS audio")
        try:
            request = LipSyncRequest.model_validate(job.params["lipsync_request"])
        except (KeyError, ValueError) as exc:
            raise ValueError("LIPSYNC_GENERATE requires a valid lipsync_request") from exc
        video_assets = [item for item in job.input_assets if item.media_type.startswith("video/")]
        audio_assets = [item for item in job.input_assets if item.media_type.startswith("audio/")]
        if len(video_assets) != 1 or len(audio_assets) != 1:
            raise ValueError("LIPSYNC_GENERATE inputs must contain one video and one audio")
        source_video = _local_path(video_assets[0].uri)
        audio = _local_path(audio_assets[0].uri)
        output_directory = _local_path(job.output_prefix) / str(request.features.shot_id)
        candidates = self.lipsync.render(
            request, source_video, audio, output_directory
        )
        variants: list[VariantResult] = []
        for candidate in candidates:
            deviation = abs(
                candidate.duration_seconds - request.source_video_duration_seconds
            ) / request.source_video_duration_seconds
            if deviation > request.decision.maximum_duration_deviation:
                raise ValueError("lipsync candidate duration exceeds route tolerance")
            path = _local_path(candidate.video_uri)
            variants.append(
                VariantResult(
                    variant_no=candidate.variant_no,
                    seed=candidate.seed,
                    output_assets=[
                        AssetRef(
                            uri=candidate.video_uri,
                            sha256=candidate.video_sha256,
                            media_type="video/mp4",
                            size_bytes=path.stat().st_size,
                            metadata={
                                "shot_id": str(candidate.shot_id),
                                "lipsync_level": candidate.level,
                                "model_release": candidate.model_release,
                                "adopted_tts_variant_id": str(
                                    request.adopted_tts_variant_id
                                ),
                            },
                        )
                    ],
                    raw_metrics={
                        "duration_seconds": candidate.duration_seconds,
                        "duration_deviation": deviation,
                        "lipsync_level": candidate.level,
                    },
                )
            )
        return StageResult(
            stage_run_id=job.stage_run_id,
            stage_attempt_id=job.stage_attempt_id,
            status="OUTPUT_READY",
            variants=variants,
            domain_artifacts=[
                DomainArtifact(
                    document_type="LIPSYNC_CANDIDATES",
                    episode_id=job.episode_id,
                    source_asset_sha256=request.source_video_sha256,
                    payload={
                        "shot_id": str(request.features.shot_id),
                        "level": request.decision.level,
                        "reason_codes": request.decision.reason_codes,
                        "router_release": job.params.get("router_release"),
                        "adopted_tts_variant_id": str(request.adopted_tts_variant_id),
                        "rights_release_id": str(request.rights.rights_release_id),
                        "rights_state_version": request.rights.state_version,
                        "model_release": self.lipsync.model_release,
                        "candidate_count": len(candidates),
                    },
                )
            ],
            attempt_usage={"worker": "production", "local": True},
        )


def _local_path(uri: str) -> Path:
    parsed = urlparse(uri)
    if parsed.scheme not in {"", "file"}:
        raise ValueError("production worker requires a local file URI")
    return Path(unquote(parsed.path if parsed.scheme else uri))
