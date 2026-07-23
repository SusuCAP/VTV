from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import modal

APP_NAME = "vtv-production"
ROOT = Path(__file__).resolve().parents[1]
REMOTE_ROOT = "/opt/vtv"

# Production worker: TTS + Lipsync
SOURCE_PATHS = (
    "packages/schemas/src",
    "packages/production/src",
    "packages/storage/src",
    "packages/media/src",
    "workers/production/src",
    "workers/media/src",
    "apps/orchestrator/src",
)

image = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install("ffmpeg", "libsndfile1")
    .uv_pip_install(
        "accelerate==1.14.0",
        "boto3==1.40.61",
        "httpx==0.28.1",
        "pydantic==2.12.3",
        "pydantic-settings==2.11.0",
        "soundfile==0.13.1",
        "torch==2.7.0",
        "torchaudio==2.7.0",
        "transformers==5.14.1",
        # CosyVoice3 will be installed from source in the volume setup task
        # LatentSync dependencies
        "einops==0.8.1",
        "omegaconf==2.3.0",
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

_VOLUME_NAME = os.getenv("VTV_MODAL_PRODUCTION_VOLUME", "vtv-models-production")
try:
    production_volume = modal.Volume.from_name(_VOLUME_NAME, create_if_missing=True)
    volume_mounts = {"/models": production_volume.with_mount_options(read_only=True)}
except Exception:
    volume_mounts = {}


@app.function(
    image=image,
    gpu="L40S",
    cpu=4.0,
    memory=24576,
    timeout=3600,
    retries=2,
    secrets=runtime_secrets,
    volumes=volume_mounts,
)
def execute_production_stage(job_payload: dict[str, Any]) -> dict[str, Any]:
    """Execute one production stage (TTS_GENERATE or LIPSYNC_GENERATE)."""
    import boto3
    from vtv_orchestrator.stage_router import StageRouter
    from vtv_production_worker import execute as execute_production
    from vtv_schemas.jobs import StageJob
    from vtv_storage import S3ObjectStore

    job = StageJob.model_validate(job_payload)
    required = ("VTV_S3_ACCESS_KEY", "VTV_S3_SECRET_KEY", "VTV_S3_BUCKET")
    missing = [n for n in required if not os.getenv(n)]
    object_store = None
    if not missing:
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
        production_executor=execute_production,
        object_store=object_store,
    ).execute(job)
    return result.model_dump(mode="json")


@app.function(image=modal.Image.debian_slim(python_version="3.12"), timeout=60)
def health() -> dict[str, str]:
    return {"service": APP_NAME, "status": "ok"}
