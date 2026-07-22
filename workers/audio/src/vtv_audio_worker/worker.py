from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
from urllib.parse import unquote, urlparse

from vtv_audio import (
    DemucsStemAdapter,
    LazyDemucsBackend,
    PassthroughDialogueAdapter,
    StemSeparationAdapter,
)
from vtv_schemas.jobs import AssetRef, DomainArtifact, StageJob, StageResult, VariantResult

from .config import Settings, get_settings


def _local_path(uri: str) -> Path:
    parsed = urlparse(uri)
    if parsed.scheme not in {"", "file"}:
        raise ValueError(f"audio worker cannot resolve URI scheme: {parsed.scheme}")
    return Path(unquote(parsed.path if parsed.scheme else uri))


def _asset(path: Path, stem_kind: str, model_release: str) -> AssetRef:
    digest = sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(4 * 1024 * 1024):
            digest.update(chunk)
    return AssetRef(
        uri=path.resolve().as_uri(),
        sha256=digest.hexdigest(),
        media_type="audio/wav",
        size_bytes=path.stat().st_size,
        metadata={"stem_kind": stem_kind, "model_release": model_release},
    )


@dataclass(frozen=True, slots=True)
class AudioWorker:
    adapter: StemSeparationAdapter = field(default_factory=PassthroughDialogueAdapter)

    def execute(self, job: StageJob) -> StageResult:
        if job.stage_type != "AUDIO_STEM_SEPARATION":
            raise ValueError(f"unsupported audio stage: {job.stage_type}")
        if len(job.input_assets) != 1:
            raise ValueError("AUDIO_STEM_SEPARATION requires exactly one media input")
        source = _local_path(job.input_assets[0].uri)
        output_directory = _local_path(job.output_prefix)
        output_directory.mkdir(parents=True, exist_ok=True)
        separated = self.adapter.separate(source, output_directory)
        assets = [
            _asset(stem.path, stem.kind, separated.model_release) for stem in separated.stems
        ]
        payload = {
            "source_duration_seconds": separated.source_duration_seconds,
            "model_release": separated.model_release,
            "stems": [
                {
                    "kind": stem.kind,
                    "sha256": asset.sha256,
                    "duration_seconds": stem.duration_seconds,
                    "channels": stem.channels,
                    "sample_rate": stem.sample_rate,
                }
                for stem, asset in zip(separated.stems, assets, strict=True)
            ],
        }
        source_hash = job.input_assets[0].sha256
        return StageResult(
            stage_run_id=job.stage_run_id,
            stage_attempt_id=job.stage_attempt_id,
            status="OUTPUT_READY",
            variants=[
                VariantResult(
                    variant_no=1,
                    output_assets=assets,
                    raw_metrics={
                        "worker": "audio",
                        "stage_type": job.stage_type,
                        "stem_count": len(assets),
                        "model_release": separated.model_release,
                    },
                )
            ],
            domain_artifacts=[
                DomainArtifact(
                    document_type="AUDIO_STEMS",
                    episode_id=job.episode_id,
                    source_asset_sha256=source_hash,
                    payload=payload,
                )
            ],
            attempt_usage={"worker": "audio", "local": True},
        )


def create_audio_worker(settings: Settings | None = None) -> AudioWorker:
    settings = settings or get_settings()
    if settings.stem_adapter_mode == "passthrough":
        return AudioWorker()
    return AudioWorker(
        DemucsStemAdapter(
            LazyDemucsBackend(
                model_name=settings.demucs_model_name,
                device=settings.demucs_device,
            ),
            settings.demucs_release,
        )
    )


def create_audio_worker_for_job(
    job: StageJob, settings: Settings | None = None
) -> AudioWorker:
    settings = settings or get_settings()
    runtime = job.params.get("model_runtime")
    if not isinstance(runtime, dict):
        return create_audio_worker(settings)
    config = runtime.get("config") if isinstance(runtime.get("config"), dict) else {}
    if config.get("adapter_mode") != "demucs":
        raise ValueError("AUDIO_STEM_SEPARATION registry release must select demucs")
    return AudioWorker(
        DemucsStemAdapter(
            LazyDemucsBackend(
                model_name=str(config.get("model_name") or settings.demucs_model_name),
                device=settings.demucs_device,
            ),
            str(runtime.get("release") or settings.demucs_release),
        )
    )


def execute(job: StageJob) -> StageResult:
    return create_audio_worker_for_job(job).execute(job)
