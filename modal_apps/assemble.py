from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import modal

APP_NAME = "vtv-assemble"
ROOT = Path(__file__).resolve().parents[1]
REMOTE_ROOT = "/opt/vtv"

# Assembly worker: subtitle render + audio mix + FFmpeg episode assembly
# CPU-only — no GPU needed
SOURCE_PATHS = (
    "packages/schemas/src",
    "packages/assembly/src",
    "packages/media/src",
    "packages/storage/src",
    "packages/markets/src",
    "workers/assemble/src",
    "workers/media/src",
    "apps/orchestrator/src",
)

image = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install("ffmpeg", "fonts-noto", "fonts-noto-cjk")
    .uv_pip_install(
        "boto3==1.40.61",
        "httpx==0.28.1",
        "Pillow==11.2.1",
        "pydantic==2.12.3",
        "pydantic-settings==2.11.0",
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
    # CPU-only: episode assembly is FFmpeg + Pillow, no GPU required
    cpu=8.0,
    memory=16384,
    ephemeral_disk=51200,  # 50 GiB for temporary video files
    timeout=7200,
    retries=2,
    secrets=runtime_secrets,
)
def execute_assemble_stage(job_payload: dict[str, Any]) -> dict[str, Any]:
    """Execute one assembly stage: SUBTITLE_RENDER, AUDIO_MIX, PICTURE_CONFORM, ASSEMBLE_EPISODE,
    or DELIVERY_EVIDENCE."""
    import boto3
    from vtv_assemble_worker import execute as execute_assemble
    from vtv_orchestrator.stage_router import StageRouter
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
        assembly_executor=execute_assemble,
        object_store=object_store,
    ).execute(job)
    return result.model_dump(mode="json")


@app.function(image=modal.Image.debian_slim(python_version="3.12"), timeout=60)
def health() -> dict[str, str]:
    return {"service": APP_NAME, "status": "ok"}
