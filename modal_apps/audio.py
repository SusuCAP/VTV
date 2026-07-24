import json
import os
from pathlib import Path
from time import perf_counter
from types import SimpleNamespace
from typing import Any

import modal

APP_NAME = "vtv-audio"
ROOT = Path(__file__).resolve().parents[1]
REMOTE_ROOT = "/opt/vtv"

# Only the packages needed for audio: stem separation + ASR/VAD
SOURCE_PATHS = (
    "packages/schemas/src",
    "packages/analysis/src",
    "packages/audio/src",
    "packages/media/src",
    "packages/storage/src",
    "workers/analysis/src",
    "workers/audio/src",
    "apps/orchestrator/src",
)

image = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install("ffmpeg")
    .uv_pip_install(
        "boto3==1.40.61",
        "demucs==4.1.0",
        "faster-whisper==1.2.1",
        "httpx==0.28.1",
        "pydantic==2.12.3",
        "pydantic-settings==2.11.0",
        "pyannote.audio==4.0.7",
        "torchaudio==2.7.0",
    )
    .env({"PYTHONPATH": ":".join(f"{REMOTE_ROOT}/{p}" for p in SOURCE_PATHS)})
)
for source_path in SOURCE_PATHS:
    image = image.add_local_dir(
        ROOT / source_path,
        remote_path=f"{REMOTE_ROOT}/{source_path}",
        copy=True,
    )

secret_name = os.getenv("VTV_MODAL_SECRET_NAME")
runtime_secrets = [modal.Secret.from_name(secret_name)] if secret_name else []
app = modal.App(APP_NAME)

_VOLUME_NAME = os.getenv("VTV_MODAL_AUDIO_VOLUME", "vtv-models-audio")
audio_volume = modal.Volume.from_name(_VOLUME_NAME, create_if_missing=False)
volume_mounts = {"/models": audio_volume.with_mount_options(read_only=True)}


@app.cls(
    image=image,
    gpu="L4",
    cpu=4.0,
    memory=16384,
    timeout=3600,
    retries=2,
    secrets=runtime_secrets,
    volumes=volume_mounts,
    startup_timeout=1200,
    max_containers=4,
    scaledown_window=300,
    buffer_containers=1,
)
class AudioStageWorker:
    stage_type: str = modal.parameter()
    runtime_json: str = modal.parameter()
    workload_json: str = modal.parameter()

    @modal.enter()
    def load(self) -> None:
        started = perf_counter()
        import boto3
        from vtv_analysis_worker.factory import create_analysis_worker_for_job
        from vtv_audio_worker.worker import create_audio_worker_for_job
        from vtv_orchestrator.stage_router import StageRouter
        from vtv_storage import S3ObjectStore

        required = ("VTV_S3_ACCESS_KEY", "VTV_S3_SECRET_KEY", "VTV_S3_BUCKET")
        missing = [name for name in required if not os.getenv(name)]
        if missing:
            raise RuntimeError(
                f"Modal runtime is missing required object-store settings: {missing}"
            )
        runtime = json.loads(self.runtime_json)
        if not isinstance(runtime, dict):
            raise ValueError("audio worker runtime parameter must be a JSON object")
        params = {"model_runtime": runtime} if runtime else {}
        pseudo_job = SimpleNamespace(stage_type=self.stage_type, params=params)
        analysis_executor = None
        audio_executor = None
        if self.stage_type == "ASR_ALIGN":
            worker = create_analysis_worker_for_job(pseudo_job)
            worker.preload()
            analysis_executor = worker.execute
        elif self.stage_type == "AUDIO_STEM_SEPARATION":
            worker = create_audio_worker_for_job(pseudo_job)
            worker.preload()
            audio_executor = worker.execute
        else:
            raise ValueError(f"unsupported audio worker stage: {self.stage_type}")
        client = boto3.client(
            "s3",
            endpoint_url=os.getenv("VTV_S3_ENDPOINT"),
            region_name=os.getenv("VTV_S3_REGION", "us-east-1"),
            aws_access_key_id=os.environ["VTV_S3_ACCESS_KEY"],
            aws_secret_access_key=os.environ["VTV_S3_SECRET_KEY"],
        )
        router_kwargs = {
            "object_store": S3ObjectStore(client, os.environ["VTV_S3_BUCKET"])
        }
        if analysis_executor is not None:
            router_kwargs["analysis_executor"] = analysis_executor
        if audio_executor is not None:
            router_kwargs["audio_executor"] = audio_executor
        self._router = StageRouter(Path("/tmp/vtv-work"), **router_kwargs)
        self._worker_init_ms = int((perf_counter() - started) * 1000)

    @modal.method()
    def run(self, job_payload: dict[str, Any]) -> dict[str, Any]:
        from vtv_orchestrator.modal_executor import modal_workload_json
        from vtv_schemas.jobs import StageJob

        job = StageJob.model_validate(job_payload)
        if job.stage_type != self.stage_type:
            raise ValueError("job stage type does not match the bound Modal worker")
        runtime = job.params.get("model_runtime")
        canonical_runtime = json.dumps(
            runtime if isinstance(runtime, dict) else {},
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )
        if canonical_runtime != self.runtime_json:
            raise ValueError("job model runtime does not match the bound Modal worker")
        if modal_workload_json(job) != self.workload_json:
            raise ValueError("job workload shape does not match the bound Modal worker")
        result = self._router.execute(job)
        usage = {
            **result.attempt_usage,
            "modal_class": type(self).__name__,
            "worker_init_ms": self._worker_init_ms,
        }
        return result.model_copy(update={"attempt_usage": usage}).model_dump(mode="json")


@app.function(image=modal.Image.debian_slim(python_version="3.12"), timeout=60)
def health() -> dict[str, str]:
    return {"service": APP_NAME, "status": "ok"}
