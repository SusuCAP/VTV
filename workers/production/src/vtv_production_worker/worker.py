from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlparse

from vtv_production import TtsAdapter, TtsRequest
from vtv_schemas.jobs import AssetRef, DomainArtifact, StageJob, StageResult, VariantResult


@dataclass(frozen=True, slots=True)
class ProductionWorker:
    tts: TtsAdapter

    def execute(self, job: StageJob) -> StageResult:
        if job.stage_type != "TTS_GENERATE":
            raise ValueError(f"unsupported production stage: {job.stage_type}")
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


def _local_path(uri: str) -> Path:
    parsed = urlparse(uri)
    if parsed.scheme not in {"", "file"}:
        raise ValueError("production worker requires a local file URI")
    return Path(unquote(parsed.path if parsed.scheme else uri))
