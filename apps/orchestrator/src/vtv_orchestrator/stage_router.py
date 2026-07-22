from collections.abc import Callable
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from urllib.parse import unquote, urlparse

from vtv_analysis_worker import execute as execute_analysis
from vtv_audio_worker import execute as execute_audio
from vtv_media_worker import execute as execute_media
from vtv_production_worker import execute as execute_production
from vtv_schemas.jobs import AssetRef, StageJob, StageResult, VariantResult
from vtv_storage import WorkerObjectStoreAdapter

from .mock_worker import execute as execute_mock

MEDIA_STAGES = frozenset({"INGEST_VALIDATE", "PROXY_GENERATE", "SHOT_DETECT"})
ANALYSIS_STAGES = frozenset({"ASR_ALIGN", "VISION_ANALYSIS", "PROJECT_SYNTHESIS"})
AUDIO_STAGES = frozenset({"AUDIO_STEM_SEPARATION"})
PRODUCTION_STAGES = frozenset({"TTS_GENERATE"})


@dataclass(frozen=True, slots=True)
class StageRouter:
    work_root: Path
    media_executor: Callable[[StageJob], StageResult] = execute_media
    analysis_executor: Callable[[StageJob], StageResult] = execute_analysis
    audio_executor: Callable[[StageJob], StageResult] = execute_audio
    production_executor: Callable[[StageJob], StageResult] = execute_production
    fallback_executor: Callable[[StageJob], StageResult] = execute_mock
    object_store: WorkerObjectStoreAdapter | None = None

    def execute(self, job: StageJob) -> StageResult:
        try:
            if job.stage_type in MEDIA_STAGES:
                return self._upload_outputs(job, self.media_executor(self._prepare_job(job)))
            if job.stage_type in ANALYSIS_STAGES:
                return self._upload_outputs(job, self.analysis_executor(self._prepare_job(job)))
            if job.stage_type in AUDIO_STAGES:
                return self._upload_outputs(job, self.audio_executor(self._prepare_job(job)))
            if job.stage_type in PRODUCTION_STAGES:
                return self._upload_outputs(
                    job, self.production_executor(self._prepare_job(job))
                )
            return self.fallback_executor(job)
        except Exception as exc:
            return StageResult(
                stage_run_id=job.stage_run_id,
                stage_attempt_id=job.stage_attempt_id,
                status="EXECUTION_FAILED",
                error_class=type(exc).__name__,
                error_detail={"message": str(exc), "retryable": False},
                attempt_usage={"worker": "stage-router", "local": True},
            )

    def _prepare_job(self, job: StageJob) -> StageJob:
        output = (
            self.work_root
            / str(job.project_id)
            / str(job.episode_id or "project")
            / str(job.stage_run_id)
        )
        output.mkdir(parents=True, exist_ok=True)
        inputs: list[AssetRef] = []
        for index, asset in enumerate(job.input_assets, 1):
            parsed = urlparse(asset.uri)
            if parsed.scheme in {"", "file"}:
                inputs.append(asset)
                continue
            if parsed.scheme != "s3" or self.object_store is None:
                raise ValueError(f"no worker materializer configured for input URI: {asset.uri}")
            filename = Path(unquote(parsed.path)).name or f"asset-{index}"
            destination = output / "inputs" / f"{index:03d}-{filename}"
            self.object_store.download_file(
                object_uri=asset.uri,
                destination=destination,
                expected_sha256=asset.sha256,
                expected_size_bytes=asset.size_bytes,
            )
            inputs.append(asset.model_copy(update={"uri": destination.resolve().as_uri()}))
        return job.model_copy(
            update={"output_prefix": output.resolve().as_uri(), "input_assets": inputs}
        )

    def _upload_outputs(self, job: StageJob, result: StageResult) -> StageResult:
        if result.status != "OUTPUT_READY" or self.object_store is None:
            return result
        variants: list[VariantResult] = []
        for variant in result.variants:
            uploaded: list[AssetRef] = []
            for asset in variant.output_assets:
                parsed = urlparse(asset.uri)
                if parsed.scheme == "s3":
                    uploaded.append(asset)
                    continue
                if parsed.scheme not in {"", "file"}:
                    raise ValueError(f"worker returned unsupported output URI: {asset.uri}")
                source = Path(unquote(parsed.path if parsed.scheme else asset.uri))
                self._verify_local_asset(source, asset)
                object_key = (
                    f"projects/{job.project_id}/episodes/{job.episode_id or 'project'}"
                    f"/stages/{job.stage_run_id}/variants/{variant.variant_no}"
                    f"/{asset.sha256}/{source.name}"
                )
                stored = self.object_store.upload_file(
                    source=source,
                    object_key=object_key,
                    content_type=asset.media_type,
                )
                uploaded.append(stored.model_copy(update={"metadata": asset.metadata}))
            variants.append(variant.model_copy(update={"output_assets": uploaded}))
        return result.model_copy(update={"variants": variants})

    @staticmethod
    def _verify_local_asset(source: Path, asset: AssetRef) -> None:
        digest = sha256()
        size = 0
        with source.open("rb") as handle:
            while chunk := handle.read(4 * 1024 * 1024):
                digest.update(chunk)
                size += len(chunk)
        if size != asset.size_bytes:
            raise ValueError(
                f"worker output size mismatch: declared {asset.size_bytes}, actual {size}"
            )
        if digest.hexdigest() != asset.sha256:
            raise ValueError("worker output SHA-256 mismatch")
