from __future__ import annotations

import os
from pathlib import Path
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


@app.function(
    image=image,
    gpu="L4",
    cpu=4.0,
    memory=16384,
    timeout=3600,
    retries=2,
    secrets=runtime_secrets,
    max_containers=4,
    scaledown_window=300,
    buffer_containers=1,
)
def execute_audio_stage(job_payload: dict[str, Any]) -> dict[str, Any]:
    """Execute one audio stage (ASR_ALIGN or AUDIO_STEM_SEPARATION) on Modal."""
    import boto3
    from vtv_analysis_worker import execute as execute_analysis
    from vtv_audio_worker import execute as execute_audio
    from vtv_orchestrator.stage_router import StageRouter
    from vtv_schemas.jobs import StageJob
    from vtv_storage import S3ObjectStore

    job = StageJob.model_validate(job_payload)
    required = ("VTV_S3_ACCESS_KEY", "VTV_S3_SECRET_KEY", "VTV_S3_BUCKET")
    missing = [n for n in required if not os.getenv(n)]
    if missing:
        raise RuntimeError(f"Modal runtime is missing required object-store settings: {missing}")
    client = boto3.client(
        "s3",
        endpoint_url=os.getenv("VTV_S3_ENDPOINT"),
        region_name=os.getenv("VTV_S3_REGION", "us-east-1"),
        aws_access_key_id=os.environ["VTV_S3_ACCESS_KEY"],
        aws_secret_access_key=os.environ["VTV_S3_SECRET_KEY"],
    )
    object_store = S3ObjectStore(client, os.environ["VTV_S3_BUCKET"])

    result = StageRouter(
        Path("/tmp/vtv-work"),
        analysis_executor=execute_analysis,
        audio_executor=execute_audio,
        object_store=object_store,
    ).execute(job)
    return result.model_dump(mode="json")


@app.function(image=modal.Image.debian_slim(python_version="3.12"), timeout=60)
def health() -> dict[str, str]:
    return {"service": APP_NAME, "status": "ok"}
