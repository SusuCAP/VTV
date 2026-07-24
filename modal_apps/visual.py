from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import modal

APP_NAME = "vtv-visual"
ROOT = Path(__file__).resolve().parents[1]
REMOTE_ROOT = "/opt/vtv"

# Visual worker needs: schemas + production (adapters) + routing + visual worker
SOURCE_PATHS = (
    "packages/schemas/src",
    "packages/production/src",
    "packages/routing/src",
    "packages/storage/src",
    "packages/media/src",
    "workers/visual/src",
    "workers/media/src",
    "apps/orchestrator/src",
)

image = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install("ffmpeg", "libgl1", "libglib2.0-0")
    .uv_pip_install(
        "accelerate==1.14.0",
        "boto3==1.40.61",
        "diffusers==0.34.0",
        "httpx==0.28.1",
        "opencv-python-headless==4.11.0.86",
        "pydantic==2.12.3",
        "pydantic-settings==2.11.0",
        # SAM3.1 — installed from HuggingFace / segment-anything-3 when available
        # For now use segment-anything as fallback
        "segment-anything==1.0",
        "timm==1.0.15",
        "torch==2.7.0",
        "torchvision==0.22.0",
        "transformers==5.14.1",
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

# Modal Volume for model weights (read-only in production)
# Create with: modal volume create vtv-models-visual
_VOLUME_NAME = os.getenv("VTV_MODAL_VISUAL_VOLUME", "vtv-models-visual")
try:
    visual_volume = modal.Volume.from_name(_VOLUME_NAME, create_if_missing=True)
    volume_mounts = {"/models": visual_volume.with_mount_options(read_only=True)}
except Exception:
    volume_mounts = {}


@app.function(
    image=image,
    gpu="L40S",
    cpu=4.0,
    memory=32768,
    timeout=7200,
    retries=2,
    secrets=runtime_secrets,
    volumes=volume_mounts,
    max_containers=8,       # visual generation is the heaviest pool
    scaledown_window=300,
    buffer_containers=1,
)
def execute_visual_stage(job_payload: dict[str, Any]) -> dict[str, Any]:
    """Execute one visual production stage (VISUAL_CHARACTER_REPLACE, VISUAL_FULL_REGEN, etc.)."""
    import boto3
    from vtv_orchestrator.stage_router import StageRouter
    from vtv_schemas.jobs import StageJob
    from vtv_storage import S3ObjectStore
    from vtv_visual_worker import execute as execute_visual

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
        visual_executor=execute_visual,
        object_store=object_store,
    ).execute(job)
    return result.model_dump(mode="json")


@app.function(image=modal.Image.debian_slim(python_version="3.12"), timeout=60)
def health() -> dict[str, str]:
    return {"service": APP_NAME, "status": "ok"}
