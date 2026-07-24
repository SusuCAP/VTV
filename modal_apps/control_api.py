from __future__ import annotations

import os
from pathlib import Path

import modal

APP_NAME = "vtv-control-api"
ROOT = Path(__file__).resolve().parents[1]
REMOTE_ROOT = "/opt/vtv"

# Keep the control-plane image intentionally small: it contains only the API and
# the domain packages imported by the PostgreSQL repository implementation.
SOURCE_PATHS = (
    "apps/control-api/src",
    "packages/db/src",
    "packages/delivery/src",
    "packages/evaluation/src",
    "packages/markets/src",
    "packages/media/src",
    "packages/production/src",
    "packages/routing/src",
    "packages/schemas/src",
    "packages/storage/src",
)

REQUIRED_SETTINGS = (
    "VTV_DATABASE_URL",
    "VTV_S3_ENDPOINT",
    "VTV_S3_ACCESS_KEY",
    "VTV_S3_SECRET_KEY",
    "VTV_S3_BUCKET",
    "VTV_API_KEY",
)

image = (
    modal.Image.debian_slim(python_version="3.12")
    .uv_pip_install(
        "asyncpg==0.31.0",
        "boto3==1.43.53",
        "fastapi==0.139.2",
        "opentelemetry-instrumentation-fastapi==0.65b0",
        "opentelemetry-sdk==1.44.0",
        "pydantic==2.13.4",
        "pydantic-settings==2.14.2",
        "sqlalchemy[asyncio]==2.0.51",
        "structlog==26.1.0",
    )
    .env({"PYTHONPATH": ":".join(f"{REMOTE_ROOT}/{path}" for path in SOURCE_PATHS)})
)
for source_path in SOURCE_PATHS:
    image = image.add_local_dir(
        ROOT / source_path,
        remote_path=f"{REMOTE_ROOT}/{source_path}",
        copy=True,
    )

secret_name = os.getenv("VTV_MODAL_SECRET_NAME", "vtv-prod-secrets")
app = modal.App(APP_NAME)


def _validate_runtime_settings() -> None:
    missing = [name for name in REQUIRED_SETTINGS if not os.getenv(name)]
    if missing:
        raise RuntimeError(
            "Modal control API is missing required production settings: "
            + ", ".join(missing)
        )
    if os.environ.get("VTV_ENVIRONMENT") != "production":
        raise RuntimeError("Modal control API requires VTV_ENVIRONMENT=production")
    if not os.environ["VTV_DATABASE_URL"].startswith("postgresql+asyncpg://"):
        raise RuntimeError("VTV_DATABASE_URL must use postgresql+asyncpg://")


@app.function(
    image=image,
    cpu=2.0,
    memory=2048,
    timeout=300,
    secrets=[modal.Secret.from_name(secret_name)],
    max_containers=8,
    scaledown_window=300,
    buffer_containers=1,
)
@modal.asgi_app()
def control_api():
    """Serve the authoritative FastAPI control plane as a Modal ASGI app."""
    _validate_runtime_settings()

    # Import only after validating injected secrets so a misconfigured
    # deployment fails before constructing database or object-store clients.
    from vtv_control_api.app import app as fastapi_app

    return fastapi_app
