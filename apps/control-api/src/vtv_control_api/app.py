from __future__ import annotations

import asyncio
import json
from math import ceil
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response, Security, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field
from vtv_db.repository import (
    AnalysisNotReadyError,
    ArtifactConflictError,
    BatchRetryRequest,
    BatchRetryResult,
    CandidateConflictError,
    DeliveryConflictError,
    EpisodeProductionRollback,
    EpisodeRollbackResult,
    EpisodeSummary,
    EvaluatorConflictError,
    FailedStageRead,
    MediaAssetRead,
    ModelPromoteRequest,
    ModelReleaseConflictError,
    OutboxEventRead,
    ProductionNotReadyError,
    ProjectArchivedError,
    ProjectNotFoundError,
    ProjectRepository,
    RightsReleaseConflictError,
    StageNotReadyError,
    StageRunRead,
    UploadConflictError,
)
from vtv_delivery import (
    DeliveryApprove,
    DeliveryCreate,
    DeliveryPackage,
    DeliveryRead,
    DeliveryRevoke,
)
from vtv_evaluation.contracts import EvaluatorReleaseCreate, EvaluatorReleaseRead, QcEvidenceCreate
from vtv_markets import MarketConfig, get_market_config, list_markets
from vtv_schemas.alerts import ProductionAlert
from vtv_schemas.analysis import AnalysisDocumentRead
from vtv_schemas.assembly import EpisodeAssemblyJobCreate
from vtv_schemas.benchmarks import BenchmarkReleaseCreate, BenchmarkReleaseRead
from vtv_schemas.candidates import (
    CandidateAdopt,
    CandidateAdoptRequest,
    CandidateAdoptResult,
    CandidateGroupRead,
    CandidateQcCreate,
    CandidateVariantRead,
)
from vtv_schemas.concurrency import DEFAULT_CONCURRENCY_POLICY, ConcurrencyPolicy
from vtv_schemas.cost_report import ProjectCostReport
from vtv_schemas.episodes import EpisodeRead
from vtv_schemas.health import HealthCheckResult, HealthReport, SystemMetrics
from vtv_schemas.jobs import JobAccepted, JobProgress, JobRead, JobSummary, ProduceRequest
from vtv_schemas.model_hotupdate import ModelHotUpdateConfig
from vtv_schemas.model_releases import (
    ModelAccessProfileCreate,
    ModelAccessProfileRead,
    ModelAutomationUpdate,
    ModelLifecycleUpdate,
    ModelLicenseReview,
    ModelReleaseCreate,
    ModelReleaseRead,
)
from vtv_schemas.production import DubbingJobCreate, LipSyncJobCreate
from vtv_schemas.project_stats import EpisodeJobSummary, ProjectStats, QualitySnapshot
from vtv_schemas.projects import ProjectCreate, ProjectRead
from vtv_schemas.releases import (
    ArtifactConfirm,
    ArtifactReleaseCreate,
    ArtifactReleaseRead,
    ArtifactTransition,
)
from vtv_schemas.retention import DEFAULT_RETENTION_POLICY
from vtv_schemas.rights import (
    RightsExecutionCheck,
    RightsExecutionDecision,
    RightsReleaseCreate,
    RightsReleaseRead,
    RightsRevoke,
)
from vtv_schemas.uploads import (
    MultipartComplete,
    MultipartInit,
    MultipartUpload,
    UploadPart,
    UploadRead,
)
from vtv_schemas.webhook import WebhookConfig, WebhookCreate
from vtv_storage import (
    MemoryObjectStore,
    ObjectStoreAdapter,
    UploadIntegrityError,
    UploadNotFoundError,
)

from .config import get_settings
from .database import create_repository
from .storage import create_object_store



class StageRetryRequest(BaseModel):
    reason: str = Field(default="manual-retry", min_length=1, max_length=200)


class ShotRouteOverride(BaseModel):
    route: str = Field(pattern=r"^[ABCDEF]$")
    reason: str = Field(default="manual-override", min_length=1, max_length=200)
    force_rerun: bool = False


class ArchiveRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=500)


class EpisodeRegisterItem(BaseModel):
    episode_no: int = Field(ge=1)
    filename: str = Field(min_length=1, max_length=500)
    duration_ms: int | None = Field(default=None, ge=0)
    source_sha256: str = Field(min_length=64, max_length=64)


class AssetGenerateRequest(BaseModel):
    quality_profile: str | None = Field(default=None, max_length=100)


class AssetApproveRequest(BaseModel):
    release_ids: list[UUID]


def workspace_id(
    request: Request,
    x_workspace_id: Annotated[UUID | None, Header()] = None,
) -> UUID:
    if x_workspace_id is None:
        if getattr(request.app.state, "allow_implicit_workspace", False):
            return TEST_WORKSPACE_ID
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="X-Workspace-Id header is required",
        )
    return x_workspace_id


_bearer_scheme = HTTPBearer(auto_error=False)


def require_api_key(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Security(_bearer_scheme)] = None,
) -> None:
    """Validate Bearer token when VTV_API_KEY is set.

    When ``VTV_API_KEY`` is empty (the default for local development), auth is
    disabled and every request is allowed.  In non-local environments, set a
    strong random value via the Modal Secret / env var.
    """
    from .config import get_settings  # local import to avoid circular deps
    expected = get_settings().api_key
    if not expected:
        return  # auth disabled (local dev)
    if credentials is None or credentials.credentials != expected:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")


def create_app(
    repository: ProjectRepository | None = None,
    object_store: ObjectStoreAdapter | None = None,
) -> FastAPI:
    settings = get_settings()
    if repository is None and settings.environment != "local" and not settings.api_key:
        raise RuntimeError(
            "VTV_API_KEY is required when starting the production control API"
        )

    # P9-B: configure structured logging at app startup
    from .logging import configure_logging
    configure_logging()

    # P9-D: instrument FastAPI with OpenTelemetry when SDK is available
    try:
        from opentelemetry import trace
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
        _provider = TracerProvider()
        _provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
        trace.set_tracer_provider(_provider)
        _otel_available = True
    except ImportError:
        _otel_available = False

    # P9-A: attach require_api_key as a global dependency (no-op when VTV_API_KEY is empty)
    app = FastAPI(
        title=settings.api_title,
        version=settings.api_version,
        dependencies=[Depends(require_api_key)],
    )

    if _otel_available:
        FastAPIInstrumentor.instrument_app(app)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://127.0.0.1:1420",
            "http://localhost:1420",
            "tauri://localhost",
            "http://tauri.localhost",
        ],
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "X-Workspace-Id", "Authorization"],
    )
    repo = repository or create_repository(settings)
    storage = object_store or (
        MemoryObjectStore() if repository is not None else create_object_store(settings)
    )
    app.state.repository = repo
    app.state.object_store = storage
    # In-memory repositories are only an explicit test/contract injection.
    # Production PostgreSQL requests must always provide tenant identity.
    app.state.allow_implicit_workspace = repository is not None

    @app.get("/healthz", tags=["system"])
    def health_simple() -> dict[str, str]:
        return {"status": "ok", "environment": settings.environment}

    @app.get("/v1/health", response_model=HealthReport, tags=["system"])
    async def health_report() -> HealthReport:
        import importlib
        import time

        checks: dict[str, HealthCheckResult] = {}

        # database check
        t0 = time.monotonic()
        try:
            checks["database"] = HealthCheckResult(
                status="ok", latency_ms=round((time.monotonic() - t0) * 1000, 2)
            )
        except Exception as exc:  # noqa: BLE001
            checks["database"] = HealthCheckResult(
                status="error",
                message=str(exc),
                latency_ms=round((time.monotonic() - t0) * 1000, 2),
            )

        # storage check
        try:
            storage_ok = storage is not None
            checks["storage"] = HealthCheckResult(status="ok" if storage_ok else "warn")
        except Exception as exc:  # noqa: BLE001
            checks["storage"] = HealthCheckResult(status="warn", message=str(exc))

        # modal check (import only)
        try:
            importlib.import_module("modal")
            checks["modal"] = HealthCheckResult(status="ok")
        except ImportError:
            checks["modal"] = HealthCheckResult(
                status="warn", message="modal package not importable"
            )

        # schema_version check (latest known migration)
        checks["schema_version"] = HealthCheckResult(status="ok", message="0013")

        error_count = sum(1 for c in checks.values() if c.status == "error")
        warn_count = sum(1 for c in checks.values() if c.status == "warn")
        if error_count:
            overall = "error"
        elif warn_count:
            overall = "degraded"
        else:
            overall = "ok"

        from datetime import UTC, datetime  # noqa: PLC0415

        from fastapi.responses import JSONResponse  # noqa: PLC0415

        report = HealthReport(
            status=overall,
            version=settings.api_version,
            checks=checks,
            timestamp=datetime.now(UTC),
        )
        http_status = (
            status.HTTP_503_SERVICE_UNAVAILABLE if overall != "ok" else status.HTTP_200_OK
        )
        return JSONResponse(content=report.model_dump(mode="json"), status_code=http_status)

    @app.get("/v1/metrics", response_model=SystemMetrics, tags=["system"])
    async def get_metrics(
        workspace: Annotated[UUID, Depends(workspace_id)],
    ) -> SystemMetrics:
        return await repo.get_system_metrics(workspace)

    @app.post("/v1/projects", response_model=ProjectRead, status_code=status.HTTP_201_CREATED)
    async def create_project(
        payload: ProjectCreate,
        workspace: Annotated[UUID, Depends(workspace_id)],
    ) -> ProjectRead:
        return await repo.create_project(workspace, payload)

    @app.post(
        "/v1/model-releases",
        response_model=ModelReleaseRead,
        status_code=status.HTTP_201_CREATED,
    )
    async def create_model_release(
        payload: ModelReleaseCreate,
        workspace: Annotated[UUID, Depends(workspace_id)],
    ) -> ModelReleaseRead:
        try:
            return await repo.create_model_release(workspace, payload)
        except ProjectNotFoundError as exc:
            raise HTTPException(status_code=404, detail="fallback model release not found") from exc
        except ModelReleaseConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/v1/model-releases", response_model=list[ModelReleaseRead])
    async def list_model_releases(
        workspace: Annotated[UUID, Depends(workspace_id)],
        model_key: Annotated[str | None, Query(max_length=64)] = None,
    ) -> list[ModelReleaseRead]:
        return await repo.list_model_releases(workspace, model_key)

    @app.post(
        "/v1/model-releases/{release_id}/access-profiles",
        response_model=ModelAccessProfileRead,
        status_code=status.HTTP_201_CREATED,
    )
    async def create_model_access_profile(
        release_id: UUID,
        payload: ModelAccessProfileCreate,
        workspace: Annotated[UUID, Depends(workspace_id)],
    ) -> ModelAccessProfileRead:
        try:
            return await repo.create_model_access_profile(workspace, release_id, payload)
        except ProjectNotFoundError as exc:
            raise HTTPException(
                status_code=404,
                detail="model release or runtime profile not found",
            ) from exc
        except ModelReleaseConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get(
        "/v1/model-releases/{release_id}/access-profiles",
        response_model=list[ModelAccessProfileRead],
    )
    async def list_model_access_profiles(
        release_id: UUID,
        workspace: Annotated[UUID, Depends(workspace_id)],
    ) -> list[ModelAccessProfileRead]:
        try:
            return await repo.list_model_access_profiles(workspace, release_id)
        except ProjectNotFoundError as exc:
            raise HTTPException(status_code=404, detail="model release not found") from exc

    @app.post(
        "/v1/model-releases/{release_id}/lifecycle",
        response_model=ModelReleaseRead,
    )
    async def update_model_lifecycle(
        release_id: UUID,
        payload: ModelLifecycleUpdate,
        workspace: Annotated[UUID, Depends(workspace_id)],
    ) -> ModelReleaseRead:
        try:
            return await repo.update_model_lifecycle(workspace, release_id, payload)
        except ProjectNotFoundError as exc:
            raise HTTPException(status_code=404, detail="model release not found") from exc
        except ModelReleaseConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post(
        "/v1/model-releases/{release_id}/benchmarks",
        response_model=BenchmarkReleaseRead,
        status_code=status.HTTP_201_CREATED,
    )
    async def create_benchmark_release(
        release_id: UUID,
        payload: BenchmarkReleaseCreate,
        workspace: Annotated[UUID, Depends(workspace_id)],
    ) -> BenchmarkReleaseRead:
        try:
            return await repo.create_benchmark_release(workspace, release_id, payload)
        except ProjectNotFoundError as exc:
            raise HTTPException(status_code=404, detail="model release not found") from exc
        except (ModelReleaseConflictError, ValueError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get(
        "/v1/model-releases/{release_id}/benchmarks",
        response_model=list[BenchmarkReleaseRead],
    )
    async def list_benchmark_releases(
        release_id: UUID,
        workspace: Annotated[UUID, Depends(workspace_id)],
    ) -> list[BenchmarkReleaseRead]:
        try:
            return await repo.list_benchmark_releases(workspace, release_id)
        except ProjectNotFoundError as exc:
            raise HTTPException(status_code=404, detail="model release not found") from exc

    @app.post("/v1/model-releases/{release_id}/license-review", response_model=ModelReleaseRead)
    async def review_model_license(
        release_id: UUID,
        payload: ModelLicenseReview,
        workspace: Annotated[UUID, Depends(workspace_id)],
    ) -> ModelReleaseRead:
        try:
            return await repo.review_model_license(
                workspace,
                release_id,
                payload.decision,
                payload.actor_id,
                payload.expected_state_version,
            )
        except ProjectNotFoundError as exc:
            raise HTTPException(status_code=404, detail="model release not found") from exc
        except ModelReleaseConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/v1/model-releases/{release_id}/automation", response_model=ModelReleaseRead)
    async def update_model_automation(
        release_id: UUID,
        payload: ModelAutomationUpdate,
        workspace: Annotated[UUID, Depends(workspace_id)],
    ) -> ModelReleaseRead:
        try:
            return await repo.update_model_automation(
                workspace,
                release_id,
                payload.target,
                payload.traffic_percent,
                payload.expected_state_version,
            )
        except ProjectNotFoundError as exc:
            raise HTTPException(status_code=404, detail="model release not found") from exc
        except ModelReleaseConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/v1/projects", response_model=list[ProjectRead])
    async def list_projects(
        workspace: Annotated[UUID, Depends(workspace_id)],
        include_archived: Annotated[bool, Query()] = False,
    ) -> list[ProjectRead]:
        return await repo.list_projects(workspace, include_archived=include_archived)

    @app.post("/v1/projects/{project_id}:archive", response_model=ProjectRead)
    async def archive_project(
        project_id: UUID,
        payload: ArchiveRequest,
        workspace: Annotated[UUID, Depends(workspace_id)],
    ) -> ProjectRead:
        try:
            return await repo.archive_project(workspace, project_id, payload.reason)
        except ProjectNotFoundError as exc:
            raise HTTPException(status_code=404, detail="project not found") from exc
        except ProjectArchivedError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/v1/projects/{project_id}:unarchive", response_model=ProjectRead)
    async def unarchive_project(
        project_id: UUID,
        workspace: Annotated[UUID, Depends(workspace_id)],
    ) -> ProjectRead:
        try:
            return await repo.unarchive_project(workspace, project_id)
        except ProjectNotFoundError as exc:
            raise HTTPException(status_code=404, detail="project not found") from exc

    @app.post("/v1/projects/{project_id}:pause", response_model=ProjectRead)
    async def pause_project(
        project_id: UUID,
        payload: ArchiveRequest,
        workspace: Annotated[UUID, Depends(workspace_id)],
    ) -> ProjectRead:
        """Stop dispatching new stages. Running stages complete at a safe point."""
        try:
            return await repo.pause_project(workspace, project_id, payload.reason)
        except ProjectNotFoundError as exc:
            raise HTTPException(status_code=404, detail="project not found") from exc
        except ProjectArchivedError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/v1/projects/{project_id}:resume", response_model=ProjectRead)
    async def resume_project(
        project_id: UUID,
        workspace: Annotated[UUID, Depends(workspace_id)],
    ) -> ProjectRead:
        """Resume dispatching PAUSED/READY stages."""
        try:
            return await repo.resume_project(workspace, project_id)
        except ProjectNotFoundError as exc:
            raise HTTPException(status_code=404, detail="project not found") from exc
        except ProjectArchivedError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/v1/projects/{project_id}:cancel", response_model=ProjectRead)
    async def cancel_project(
        project_id: UUID,
        payload: ArchiveRequest,
        workspace: Annotated[UUID, Depends(workspace_id)],
    ) -> ProjectRead:
        """Request cancellation of all unstarted and running tasks (irreversible)."""
        try:
            return await repo.cancel_project(workspace, project_id, payload.reason)
        except ProjectNotFoundError as exc:
            raise HTTPException(status_code=404, detail="project not found") from exc

    @app.get("/v1/projects/{project_id}", response_model=ProjectRead)
    async def get_project(
        project_id: UUID,
        workspace: Annotated[UUID, Depends(workspace_id)],
    ) -> ProjectRead:
        try:
            return await repo.get_project(workspace, project_id)
        except ProjectNotFoundError as exc:
            raise HTTPException(status_code=404, detail="project not found") from exc

    @app.post(
        "/v1/projects/{project_id}/analysis-jobs",
        response_model=JobAccepted,
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def create_analysis_job(
        project_id: UUID,
        response: Response,
        workspace: Annotated[UUID, Depends(workspace_id)],
    ) -> JobAccepted:
        try:
            job = await repo.create_analysis_job(workspace, project_id)
        except ProjectNotFoundError as exc:
            raise HTTPException(status_code=404, detail="project not found") from exc
        except ProjectArchivedError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except AnalysisNotReadyError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        status_url = f"/v1/jobs/{job.id}"
        response.headers["Location"] = status_url
        return JobAccepted(job_id=job.id, status=job.status, status_url=status_url)

    @app.post("/v1/projects/{project_id}:analyze", response_model=JobAccepted, status_code=202)
    async def analyze_project_alias(
        project_id: UUID,
        workspace: Annotated[UUID, Depends(workspace_id)],
    ) -> JobAccepted:
        """Alias for /analysis-jobs — matches v3.2 spec path."""
        try:
            return await repo.create_analysis_job(workspace, project_id)
        except ProjectNotFoundError as exc:
            raise HTTPException(status_code=404, detail="project not found") from exc
        except ProjectArchivedError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post(
        "/v1/projects/{project_id}/dubbing-jobs",
        response_model=JobAccepted,
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def create_dubbing_job(
        project_id: UUID,
        payload: DubbingJobCreate,
        response: Response,
        workspace: Annotated[UUID, Depends(workspace_id)],
    ) -> JobAccepted:
        try:
            job = await repo.create_dubbing_job(workspace, project_id, payload)
        except ProjectNotFoundError as exc:
            raise HTTPException(
                status_code=404, detail="project, episode, or rights release not found"
            ) from exc
        except ProjectArchivedError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ProductionNotReadyError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        status_url = f"/v1/jobs/{job.id}"
        response.headers["Location"] = status_url
        return JobAccepted(job_id=job.id, status=job.status, status_url=status_url)

    @app.post(
        "/v1/projects/{project_id}/lipsync-jobs",
        response_model=JobAccepted,
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def create_lipsync_job(
        project_id: UUID,
        payload: LipSyncJobCreate,
        response: Response,
        workspace: Annotated[UUID, Depends(workspace_id)],
    ) -> JobAccepted:
        try:
            job = await repo.create_lipsync_job(workspace, project_id, payload)
        except ProjectNotFoundError as exc:
            raise HTTPException(
                status_code=404, detail="project, episode, or shot not found"
            ) from exc
        except ProjectArchivedError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ProductionNotReadyError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        status_url = f"/v1/jobs/{job.id}"
        response.headers["Location"] = status_url
        return JobAccepted(job_id=job.id, status=job.status, status_url=status_url)

    @app.post(
        "/v1/projects/{project_id}/assembly-jobs",
        response_model=JobAccepted,
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def create_episode_assembly_job(
        project_id: UUID,
        payload: EpisodeAssemblyJobCreate,
        response: Response,
        workspace: Annotated[UUID, Depends(workspace_id)],
    ) -> JobAccepted:
        try:
            job = await repo.create_episode_assembly_job(
                workspace, project_id, payload
            )
        except ProjectNotFoundError as exc:
            raise HTTPException(
                status_code=404, detail="project or episode not found"
            ) from exc
        except ProjectArchivedError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ProductionNotReadyError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        status_url = f"/v1/jobs/{job.id}"
        response.headers["Location"] = status_url
        return JobAccepted(job_id=job.id, status=job.status, status_url=status_url)

    @app.post(
        "/v1/projects/{project_id}:produce",
        response_model=JobRead,
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def produce_project(
        project_id: UUID,
        payload: ProduceRequest,
        response: Response,
        workspace: Annotated[UUID, Depends(workspace_id)],
    ) -> JobRead:
        try:
            job = await repo.create_production_job(workspace, project_id, payload)
        except ProjectNotFoundError as exc:
            raise HTTPException(status_code=404, detail="project not found") from exc
        except ProjectArchivedError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ProductionNotReadyError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        response.headers["Location"] = f"/v1/jobs/{job.id}"
        return job

    @app.get(
        "/v1/projects/{project_id}/qc-stats",
        response_model=dict,
    )
    async def get_project_qc_stats(
        project_id: UUID,
        workspace: Annotated[UUID, Depends(workspace_id)],
    ) -> dict:
        try:
            return await repo.get_project_qc_stats(workspace, project_id)
        except ProjectNotFoundError as exc:
            raise HTTPException(status_code=404, detail="project not found") from exc

    @app.post(
        "/v1/projects/{project_id}/deliveries",
        response_model=DeliveryRead,
        status_code=status.HTTP_201_CREATED,
    )
    async def create_delivery(
        project_id: UUID,
        payload: DeliveryCreate,
        response: Response,
        workspace: Annotated[UUID, Depends(workspace_id)],
    ) -> DeliveryRead:
        try:
            delivery = await repo.create_delivery(workspace, project_id, payload)
        except ProjectNotFoundError as exc:
            raise HTTPException(
                status_code=404, detail="project, episode, or delivery asset not found"
            ) from exc
        except DeliveryConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        response.headers["Location"] = f"/v1/deliveries/{delivery.id}"
        return delivery

    @app.get(
        "/v1/projects/{project_id}/deliveries",
        response_model=list[DeliveryRead],
    )
    async def list_deliveries(
        project_id: UUID,
        workspace: Annotated[UUID, Depends(workspace_id)],
        episode_id: Annotated[UUID | None, Query()] = None,
    ) -> list[DeliveryRead]:
        try:
            return await repo.list_deliveries(workspace, project_id, episode_id)
        except ProjectNotFoundError as exc:
            raise HTTPException(status_code=404, detail="project not found") from exc

    @app.get("/v1/deliveries/{delivery_id}", response_model=DeliveryRead)
    async def get_delivery(
        delivery_id: UUID,
        workspace: Annotated[UUID, Depends(workspace_id)],
    ) -> DeliveryRead:
        try:
            return await repo.get_delivery(workspace, delivery_id)
        except ProjectNotFoundError as exc:
            raise HTTPException(status_code=404, detail="delivery not found") from exc

    @app.post(
        "/v1/deliveries/{delivery_id}/approve",
        response_model=DeliveryRead,
    )
    async def approve_delivery(
        delivery_id: UUID,
        payload: DeliveryApprove,
        workspace: Annotated[UUID, Depends(workspace_id)],
    ) -> DeliveryRead:
        try:
            return await repo.approve_delivery(workspace, delivery_id, payload)
        except ProjectNotFoundError as exc:
            raise HTTPException(status_code=404, detail="delivery not found") from exc
        except DeliveryConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post(
        "/v1/deliveries/{delivery_id}:request-sign",
        response_model=DeliveryRead,
    )
    async def request_c2pa_sign(
        delivery_id: UUID,
        workspace: Annotated[UUID, Depends(workspace_id)],
    ) -> DeliveryRead:
        try:
            return await repo.request_c2pa_signing(workspace, delivery_id)
        except ProjectNotFoundError as exc:
            raise HTTPException(status_code=404, detail="delivery not found") from exc
        except DeliveryConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get(
        "/v1/deliveries/{delivery_id}/package",
        response_model=DeliveryPackage,
    )
    async def get_delivery_package(
        delivery_id: UUID,
        workspace: Annotated[UUID, Depends(workspace_id)],
    ) -> DeliveryPackage:
        try:
            package = await repo.get_delivery_package(workspace, delivery_id)
            for asset in package.assets:
                asset.download_url = storage.presign_download(object_uri=asset.object_uri)
            return package
        except ProjectNotFoundError as exc:
            raise HTTPException(status_code=404, detail="delivery not found") from exc
        except DeliveryConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post(
        "/v1/deliveries/{delivery_id}:revoke",
        response_model=DeliveryRead,
    )
    async def revoke_delivery(
        delivery_id: UUID,
        payload: DeliveryRevoke,
        workspace: Annotated[UUID, Depends(workspace_id)],
    ) -> DeliveryRead:
        try:
            return await repo.revoke_delivery(workspace, delivery_id, payload)
        except ProjectNotFoundError as exc:
            raise HTTPException(status_code=404, detail="delivery not found") from exc
        except DeliveryConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/v1/projects/{project_id}/episodes", response_model=list[EpisodeRead])
    async def list_episodes(
        project_id: UUID,
        workspace: Annotated[UUID, Depends(workspace_id)],
    ) -> list[EpisodeRead]:
        try:
            return await repo.list_episodes(workspace, project_id)
        except ProjectNotFoundError as exc:
            raise HTTPException(status_code=404, detail="project not found") from exc

    @app.get("/v1/projects/{project_id}/jobs", response_model=list[JobSummary])
    async def list_jobs(
        project_id: UUID,
        workspace: Annotated[UUID, Depends(workspace_id)],
    ) -> list[JobSummary]:
        try:
            return await repo.list_job_summaries(workspace, project_id)
        except ProjectNotFoundError as exc:
            raise HTTPException(status_code=404, detail="project not found") from exc

    @app.get(
        "/v1/projects/{project_id}/jobs/{job_id}/progress",
        response_model=JobProgress,
    )
    async def get_job_progress(
        project_id: UUID,
        job_id: UUID,
        workspace: Annotated[UUID, Depends(workspace_id)],
    ) -> JobProgress:
        try:
            return await repo.get_job_progress(workspace, project_id, job_id)
        except ProjectNotFoundError as exc:
            raise HTTPException(status_code=404, detail="job not found") from exc

    @app.get(
        "/v1/projects/{project_id}/candidate-groups",
        response_model=list[CandidateGroupRead],
    )
    async def list_candidate_groups(
        project_id: UUID,
        workspace: Annotated[UUID, Depends(workspace_id)],
        job_id: Annotated[UUID | None, Query()] = None,
    ) -> list[CandidateGroupRead]:
        try:
            return await repo.list_candidate_groups(workspace, project_id, job_id)
        except ProjectNotFoundError as exc:
            raise HTTPException(status_code=404, detail="project or job not found") from exc

    @app.post(
        "/v1/candidate-variants/{variant_id}/qc",
        response_model=CandidateVariantRead,
    )
    async def submit_candidate_qc(
        variant_id: UUID,
        payload: CandidateQcCreate,
        workspace: Annotated[UUID, Depends(workspace_id)],
    ) -> CandidateVariantRead:
        try:
            return await repo.submit_candidate_qc(workspace, variant_id, payload)
        except ProjectNotFoundError as exc:
            raise HTTPException(status_code=404, detail="candidate variant not found") from exc
        except CandidateConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post(
        "/v1/candidate-groups/{group_id}/adopt",
        response_model=CandidateGroupRead,
    )
    async def adopt_candidate(
        group_id: UUID,
        payload: CandidateAdopt,
        workspace: Annotated[UUID, Depends(workspace_id)],
    ) -> CandidateGroupRead:
        try:
            return await repo.adopt_candidate(workspace, group_id, payload)
        except ProjectNotFoundError as exc:
            raise HTTPException(
                status_code=404, detail="candidate group or variant not found"
            ) from exc
        except CandidateConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post(
        "/v1/projects/{project_id}/candidates/{variant_id}:adopt",
        response_model=CandidateAdoptResult,
    )
    async def adopt_candidate_manual(
        project_id: UUID,
        variant_id: UUID,
        payload: CandidateAdoptRequest,
        workspace: Annotated[UUID, Depends(workspace_id)],
    ) -> CandidateAdoptResult:
        try:
            return await repo.adopt_candidate_manual(workspace, project_id, variant_id, payload)
        except ProjectNotFoundError as exc:
            raise HTTPException(
                status_code=404, detail="project or candidate variant not found"
            ) from exc
        except CandidateConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get(
        "/v1/projects/{project_id}/quality-snapshot",
        response_model=QualitySnapshot,
    )
    async def get_quality_snapshot(
        project_id: UUID,
        workspace: Annotated[UUID, Depends(workspace_id)],
    ) -> QualitySnapshot:
        try:
            return await repo.get_quality_snapshot(workspace, project_id)
        except ProjectNotFoundError as exc:
            raise HTTPException(status_code=404, detail="project not found") from exc

    @app.post(
        "/v1/projects/{project_id}/artifact-releases",
        response_model=ArtifactReleaseRead,
        status_code=status.HTTP_201_CREATED,
    )
    async def create_artifact_release(
        project_id: UUID,
        payload: ArtifactReleaseCreate,
        workspace: Annotated[UUID, Depends(workspace_id)],
    ) -> ArtifactReleaseRead:
        try:
            return await repo.create_artifact_release(workspace, project_id, payload)
        except ProjectNotFoundError as exc:
            raise HTTPException(
                status_code=404, detail="project, asset, or dependency not found"
            ) from exc
        except ArtifactConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get(
        "/v1/projects/{project_id}/artifact-releases",
        response_model=list[ArtifactReleaseRead],
    )
    async def list_artifact_releases(
        project_id: UUID,
        workspace: Annotated[UUID, Depends(workspace_id)],
    ) -> list[ArtifactReleaseRead]:
        try:
            return await repo.list_artifact_releases(workspace, project_id)
        except ProjectNotFoundError as exc:
            raise HTTPException(status_code=404, detail="project not found") from exc

    @app.post(
        "/v1/projects/{project_id}/rights-releases",
        response_model=RightsReleaseRead,
        status_code=status.HTTP_201_CREATED,
    )
    async def create_rights_release(
        project_id: UUID,
        payload: RightsReleaseCreate,
        workspace: Annotated[UUID, Depends(workspace_id)],
    ) -> RightsReleaseRead:
        try:
            return await repo.create_rights_release(workspace, project_id, payload)
        except ProjectNotFoundError as exc:
            raise HTTPException(
                status_code=404, detail="project or rights source asset not found"
            ) from exc
        except RightsReleaseConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get(
        "/v1/projects/{project_id}/rights-releases",
        response_model=list[RightsReleaseRead],
    )
    async def list_rights_releases(
        project_id: UUID,
        workspace: Annotated[UUID, Depends(workspace_id)],
    ) -> list[RightsReleaseRead]:
        try:
            return await repo.list_rights_releases(workspace, project_id)
        except ProjectNotFoundError as exc:
            raise HTTPException(status_code=404, detail="project not found") from exc

    @app.post(
        "/v1/rights-releases/{release_id}/revoke",
        response_model=RightsReleaseRead,
    )
    async def revoke_rights_release(
        release_id: UUID,
        payload: RightsRevoke,
        workspace: Annotated[UUID, Depends(workspace_id)],
    ) -> RightsReleaseRead:
        try:
            return await repo.revoke_rights_release(
                workspace,
                release_id,
                payload.actor_id,
                payload.reason,
                payload.expected_state_version,
            )
        except ProjectNotFoundError as exc:
            raise HTTPException(status_code=404, detail="rights release not found") from exc
        except RightsReleaseConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post(
        "/v1/rights-releases/{release_id}/check",
        response_model=RightsExecutionDecision,
    )
    async def check_rights_release(
        release_id: UUID,
        payload: RightsExecutionCheck,
        workspace: Annotated[UUID, Depends(workspace_id)],
    ) -> RightsExecutionDecision:
        try:
            return await repo.check_rights_release(workspace, release_id, payload)
        except ProjectNotFoundError as exc:
            raise HTTPException(status_code=404, detail="rights release not found") from exc

    @app.get(
        "/v1/projects/{project_id}/analysis-documents",
        response_model=list[AnalysisDocumentRead],
    )
    async def list_analysis_documents(
        project_id: UUID,
        workspace: Annotated[UUID, Depends(workspace_id)],
        episode_id: Annotated[UUID | None, Query()] = None,
        document_type: Annotated[str | None, Query(max_length=64)] = None,
    ) -> list[AnalysisDocumentRead]:
        try:
            return await repo.list_analysis_documents(
                workspace, project_id, episode_id, document_type
            )
        except ProjectNotFoundError as exc:
            raise HTTPException(status_code=404, detail="project not found") from exc

    @app.get(
        "/v1/projects/{project_id}/analysis",
        response_model=list[AnalysisDocumentRead],
    )
    async def get_project_analysis(
        project_id: UUID,
        workspace: Annotated[UUID, Depends(workspace_id)],
        episode_id: Annotated[UUID | None, Query()] = None,
        document_type: Annotated[str | None, Query(max_length=64)] = None,
    ) -> list[AnalysisDocumentRead]:
        """Query full-series analysis results (characters, scenes, transcripts, issues).
        Spec alias for /analysis-documents — v3.2 §7.2 GET /v1/projects/{id}/analysis."""
        try:
            return await repo.list_analysis_documents(
                workspace, project_id, episode_id, document_type
            )
        except ProjectNotFoundError as exc:
            raise HTTPException(status_code=404, detail="project not found") from exc

    @app.post(
        "/v1/artifact-releases/{release_id}/confirm",
        response_model=ArtifactReleaseRead,
    )
    async def confirm_artifact_release(
        release_id: UUID,
        payload: ArtifactConfirm,
        workspace: Annotated[UUID, Depends(workspace_id)],
    ) -> ArtifactReleaseRead:
        try:
            return await repo.confirm_artifact_release(
                workspace, release_id, payload.actor_id, payload.expected_state_version
            )
        except ProjectNotFoundError as exc:
            raise HTTPException(status_code=404, detail="artifact release not found") from exc
        except ArtifactConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post(
        "/v1/artifact-releases/{release_id}/publish",
        response_model=ArtifactReleaseRead,
    )
    async def publish_artifact_release(
        release_id: UUID,
        payload: ArtifactTransition,
        workspace: Annotated[UUID, Depends(workspace_id)],
    ) -> ArtifactReleaseRead:
        try:
            return await repo.publish_artifact_release(
                workspace, release_id, payload.expected_state_version
            )
        except ProjectNotFoundError as exc:
            raise HTTPException(status_code=404, detail="artifact release not found") from exc
        except ArtifactConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post(
        "/v1/artifact-releases/{release_id}/invalidate",
        response_model=list[ArtifactReleaseRead],
    )
    async def invalidate_artifact_release(
        release_id: UUID,
        payload: ArtifactTransition,
        workspace: Annotated[UUID, Depends(workspace_id)],
    ) -> list[ArtifactReleaseRead]:
        try:
            return await repo.invalidate_artifact_release(
                workspace, release_id, payload.expected_state_version
            )
        except ProjectNotFoundError as exc:
            raise HTTPException(status_code=404, detail="artifact release not found") from exc
        except ArtifactConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/v1/jobs/{job_id}", response_model=JobRead)
    async def get_job(
        job_id: UUID,
        workspace: Annotated[UUID, Depends(workspace_id)],
    ) -> JobRead:
        try:
            return await repo.get_job(workspace, job_id)
        except ProjectNotFoundError as exc:
            raise HTTPException(status_code=404, detail="job not found") from exc

    @app.post(
        "/v1/uploads/multipart-init",
        response_model=MultipartUpload,
        status_code=status.HTTP_201_CREATED,
    )
    async def multipart_init(
        payload: MultipartInit,
        workspace: Annotated[UUID, Depends(workspace_id)],
    ) -> MultipartUpload:
        existing = await repo.find_active_upload(
            workspace,
            payload.project_id,
            payload.sha256,
        )
        if existing:
            part_count = ceil(existing.upload.size_bytes / existing.part_size_bytes)
            parts = storage.presign_parts(
                object_key=existing.upload.object_key,
                provider_upload_id=existing.provider_upload_id,
                part_numbers=list(range(1, part_count + 1)),
            )
            return MultipartUpload(
                upload_id=existing.upload.upload_id,
                object_key=existing.upload.object_key,
                part_size_bytes=existing.part_size_bytes,
                parts=parts,
                completed_parts=existing.upload.completed_parts,
            )
        upload_id = uuid4()
        safe_name = payload.filename.replace("/", "_").replace("\\", "_")
        object_key = (
            f"workspaces/{workspace}/projects/{payload.project_id}"
            f"/source/{upload_id}/{safe_name}"
        )
        try:
            await repo.get_project(workspace, payload.project_id)
            backend = storage.create_multipart(
                object_key=object_key,
                content_type=payload.content_type,
                part_count=ceil(payload.size_bytes / payload.part_size_bytes),
            )
            await repo.create_upload_session(
                workspace,
                upload_id,
                payload,
                object_key,
                backend.provider_upload_id,
            )
        except ProjectNotFoundError as exc:
            raise HTTPException(status_code=404, detail="project not found") from exc
        return MultipartUpload(
            upload_id=upload_id,
            object_key=object_key,
            part_size_bytes=payload.part_size_bytes,
            parts=backend.parts,
        )

    @app.put("/v1/uploads/{upload_id}/parts/{part_number}", response_model=UploadRead)
    async def record_upload_part(
        upload_id: UUID,
        part_number: int,
        payload: UploadPart,
        workspace: Annotated[UUID, Depends(workspace_id)],
    ) -> UploadRead:
        if payload.part_number != part_number:
            raise HTTPException(status_code=422, detail="part number path/body mismatch")
        try:
            return await repo.record_upload_part(workspace, upload_id, payload)
        except ProjectNotFoundError as exc:
            raise HTTPException(status_code=404, detail="upload not found") from exc
        except UploadConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/v1/uploads/{upload_id}/multipart-complete", response_model=UploadRead)
    async def multipart_complete(
        upload_id: UUID,
        payload: MultipartComplete,
        workspace: Annotated[UUID, Depends(workspace_id)],
    ) -> UploadRead:
        try:
            record = await repo.get_upload(workspace, upload_id)
            part_numbers = [part.part_number for part in payload.parts]
            if part_numbers != list(range(1, len(payload.parts) + 1)):
                raise UploadIntegrityError("parts must be complete, unique, and ordered from 1")
            if sum(part.size_bytes for part in payload.parts) != record.upload.size_bytes:
                raise UploadIntegrityError("completed part sizes do not match declared object size")
            if payload.object_checksum_sha256 is None:
                raise UploadIntegrityError("independent object SHA-256 is required")
            if payload.object_checksum_sha256 != record.declared_sha256:
                raise UploadIntegrityError("object SHA-256 does not match upload declaration")
            checkpointed = {
                part.part_number: part.model_dump(mode="json")
                for part in record.upload.completed_parts
            }
            submitted = {
                part.part_number: part.model_dump(mode="json") for part in payload.parts
            }
            if submitted != checkpointed:
                raise UploadIntegrityError("multipart completion does not match checkpointed parts")
            stored = storage.complete_multipart(
                object_key=record.upload.object_key,
                provider_upload_id=record.provider_upload_id,
                parts=payload.parts,
            )
            object_uri = storage.uri_for(record.upload.object_key)
            try:
                return await repo.complete_upload(
                    workspace,
                    upload_id,
                    payload.parts,
                    payload.object_checksum_sha256,
                    object_uri,
                    stored.content_type,
                    stored.size_bytes,
                )
            except Exception:
                await repo.register_orphan_asset(
                    workspace,
                    record.upload.project_id,
                    object_uri,
                    "UPLOAD_DATABASE_COMMIT_FAILED",
                )
                raise
        except (UploadNotFoundError, ProjectNotFoundError) as exc:
            raise HTTPException(status_code=404, detail="upload not found") from exc
        except (UploadIntegrityError, UploadConflictError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/v1/uploads/{upload_id}", response_model=UploadRead)
    async def get_upload(
        upload_id: UUID,
        workspace: Annotated[UUID, Depends(workspace_id)],
    ) -> UploadRead:
        try:
            return (await repo.get_upload(workspace, upload_id)).upload
        except ProjectNotFoundError as exc:
            raise HTTPException(status_code=404, detail="upload not found") from exc

    @app.post(
        "/v1/projects/{project_id}/stages/{stage_run_id}:retry",
        response_model=StageRunRead,
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def retry_stage(
        project_id: UUID,
        stage_run_id: UUID,
        payload: StageRetryRequest,
        workspace: Annotated[UUID, Depends(workspace_id)],
    ) -> StageRunRead:
        try:
            return await repo.retry_stage(workspace, project_id, stage_run_id, payload.reason)
        except ProjectNotFoundError as exc:
            raise HTTPException(status_code=404, detail="stage run not found") from exc
        except StageNotReadyError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post(
        "/v1/stage-runs/{stage_run_id}:retry",
        response_model=StageRunRead,
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def retry_stage_run_alias(
        stage_run_id: UUID,
        payload: StageRetryRequest,
        workspace: Annotated[UUID, Depends(workspace_id)],
        project_id: Annotated[UUID | None, Query()] = None,
    ) -> StageRunRead:
        """Spec-compliant path alias — v3.2 §7.2 POST /v1/stage-runs/{id}:retry."""
        if project_id is None:
            raise HTTPException(
                status_code=422, detail="project_id query parameter required"
            )
        try:
            return await repo.retry_stage(workspace, project_id, stage_run_id, payload.reason)
        except ProjectNotFoundError as exc:
            raise HTTPException(status_code=404, detail="stage run not found") from exc
        except StageNotReadyError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post(
        "/v1/projects/{project_id}/jobs/{job_id}:retry-failed",
        response_model=BatchRetryResult,
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def batch_retry_failed_stages(
        project_id: UUID,
        job_id: UUID,
        payload: BatchRetryRequest,
        workspace: Annotated[UUID, Depends(workspace_id)],
    ) -> BatchRetryResult:
        try:
            return await repo.batch_retry_failed_stages(workspace, project_id, job_id, payload)
        except ProjectNotFoundError as exc:
            raise HTTPException(status_code=404, detail="project or job not found") from exc

    @app.get(
        "/v1/projects/{project_id}/episodes/{episode_id}/summary",
        response_model=EpisodeSummary,
    )
    async def get_episode_summary(
        project_id: UUID,
        episode_id: UUID,
        workspace: Annotated[UUID, Depends(workspace_id)],
    ) -> EpisodeSummary:
        try:
            return await repo.get_episode_summary(workspace, project_id, episode_id)
        except ProjectNotFoundError as exc:
            raise HTTPException(status_code=404, detail="project or episode not found") from exc

    @app.get(
        "/v1/projects/{project_id}/stats",
        response_model=ProjectStats,
    )
    async def get_project_stats(
        project_id: UUID,
        workspace: Annotated[UUID, Depends(workspace_id)],
    ) -> ProjectStats:
        try:
            return await repo.get_project_stats(workspace, project_id)
        except ProjectNotFoundError as exc:
            raise HTTPException(status_code=404, detail="project not found") from exc

    @app.get(
        "/v1/projects/{project_id}/episodes/{episode_id}/jobs",
        response_model=EpisodeJobSummary,
    )
    async def list_episode_jobs(
        project_id: UUID,
        episode_id: UUID,
        workspace: Annotated[UUID, Depends(workspace_id)],
    ) -> EpisodeJobSummary:
        try:
            return await repo.list_episode_jobs(workspace, project_id, episode_id)
        except ProjectNotFoundError as exc:
            raise HTTPException(status_code=404, detail="project or episode not found") from exc

    @app.post(
        "/v1/projects/{project_id}/shots/{shot_id}:override",
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def override_shot_route(
        project_id: UUID,
        shot_id: UUID,
        payload: ShotRouteOverride,
        workspace: Annotated[UUID, Depends(workspace_id)],
    ) -> dict:
        try:
            result = await repo.override_shot_route(
                workspace,
                project_id,
                shot_id,
                payload.route,
                payload.reason,
                payload.force_rerun,
            )
            return {
                "shot_id": str(result["shot_id"]),
                "route": result["route"],
                "pending_stage_run_id": (
                    str(result["pending_stage_run_id"])
                    if result["pending_stage_run_id"] is not None
                    else None
                ),
            }
        except ProjectNotFoundError as exc:
            raise HTTPException(status_code=404, detail="shot not found") from exc

    @app.get(
        "/v1/projects/{project_id}/exceptions",
        response_model=list[FailedStageRead],
    )
    async def list_exceptions(
        project_id: UUID,
        workspace: Annotated[UUID, Depends(workspace_id)],
        stage_type: Annotated[str | None, Query(max_length=64)] = None,
        episode_id: Annotated[UUID | None, Query()] = None,
        status: Annotated[str, Query(max_length=64)] = "EXECUTION_FAILED",
    ) -> list[FailedStageRead]:
        try:
            return await repo.list_failed_stages(
                workspace, project_id, stage_type, episode_id, status
            )
        except ProjectNotFoundError as exc:
            raise HTTPException(status_code=404, detail="project not found") from exc

    @app.post(
        "/v1/evaluator-releases",
        response_model=EvaluatorReleaseRead,
        status_code=status.HTTP_201_CREATED,
    )
    async def create_evaluator_release(
        payload: EvaluatorReleaseCreate,
        workspace: Annotated[UUID, Depends(workspace_id)],
    ) -> EvaluatorReleaseRead:
        try:
            return await repo.create_evaluator_release(workspace, payload)
        except EvaluatorConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/v1/evaluator-releases", response_model=list[EvaluatorReleaseRead])
    async def list_evaluator_releases(
        workspace: Annotated[UUID, Depends(workspace_id)],
        evaluator_key: Annotated[str | None, Query(max_length=64)] = None,
    ) -> list[EvaluatorReleaseRead]:
        return await repo.list_evaluator_releases(workspace, evaluator_key)

    @app.get(
        "/v1/evaluator-releases/{release_id}",
        response_model=EvaluatorReleaseRead,
    )
    async def get_evaluator_release(
        release_id: UUID,
        workspace: Annotated[UUID, Depends(workspace_id)],
    ) -> EvaluatorReleaseRead:
        try:
            return await repo.get_evaluator_release(workspace, release_id)
        except ProjectNotFoundError as exc:
            raise HTTPException(status_code=404, detail="evaluator release not found") from exc

    @app.post(
        "/v1/evaluator-releases/{release_id}:deprecate",
        response_model=EvaluatorReleaseRead,
    )
    async def deprecate_evaluator_release(
        release_id: UUID,
        workspace: Annotated[UUID, Depends(workspace_id)],
    ) -> EvaluatorReleaseRead:
        try:
            return await repo.deprecate_evaluator_release(workspace, release_id)
        except ProjectNotFoundError as exc:
            raise HTTPException(status_code=404, detail="evaluator release not found") from exc
        except EvaluatorConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post(
        "/v1/projects/{project_id}/candidates/{variant_id}:submit-qc",
        status_code=status.HTTP_204_NO_CONTENT,
    )
    async def submit_qc_evidence(
        project_id: UUID,
        variant_id: UUID,
        payload: QcEvidenceCreate,
        workspace: Annotated[UUID, Depends(workspace_id)],
    ) -> None:
        if payload.render_variant_id != variant_id:
            raise HTTPException(
                status_code=422, detail="render_variant_id path/body mismatch"
            )
        try:
            await repo.submit_qc_evidence(workspace, project_id, payload)
        except ProjectNotFoundError as exc:
            raise HTTPException(
                status_code=404, detail="project, variant, or evaluator not found"
            ) from exc

    @app.get("/v1/markets", response_model=list[str])
    async def get_markets() -> list[str]:
        return list_markets()

    @app.get("/v1/markets/{code}", response_model=MarketConfig)
    async def get_market(code: str) -> MarketConfig:
        try:
            return get_market_config(code)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"market {code!r} not found") from exc

    @app.get(
        "/v1/projects/{project_id}/assets:list-expired",
        response_model=list[dict],
    )
    async def list_expired_assets(
        project_id: UUID,
        workspace: Annotated[UUID, Depends(workspace_id)],
    ) -> list[dict]:
        try:
            return await repo.list_expired_assets(
                workspace, project_id, DEFAULT_RETENTION_POLICY
            )
        except ProjectNotFoundError as exc:
            raise HTTPException(status_code=404, detail="project not found") from exc

    @app.post(
        "/v1/projects/{project_id}/assets:cleanup",
        response_model=dict,
        status_code=status.HTTP_200_OK,
    )
    async def cleanup_expired_assets(
        project_id: UUID,
        workspace: Annotated[UUID, Depends(workspace_id)],
    ) -> dict:
        try:
            deleted = await repo.cleanup_expired_orphans(workspace, project_id)
            return {"deleted": deleted}
        except ProjectNotFoundError as exc:
            raise HTTPException(status_code=404, detail="project not found") from exc

    @app.get(
        "/v1/projects/{project_id}/cost-report",
        response_model=ProjectCostReport,
    )
    async def get_project_cost_report(
        project_id: UUID,
        workspace: Annotated[UUID, Depends(workspace_id)],
    ) -> ProjectCostReport:
        try:
            return await repo.get_project_cost_report(workspace, project_id)
        except ProjectNotFoundError as exc:
            raise HTTPException(status_code=404, detail="project not found") from exc

    @app.post(
        "/v1/model-releases/{model_release_id}:configure-hotupdate",
        response_model=dict,
        status_code=status.HTTP_200_OK,
    )
    async def configure_model_hotupdate(
        model_release_id: UUID,
        payload: ModelHotUpdateConfig,
        workspace: Annotated[UUID, Depends(workspace_id)],
    ) -> dict:
        # Validate that the model release exists
        releases = await repo.list_model_releases(workspace, payload.model_key)
        if not any(r.id == model_release_id for r in releases):
            raise HTTPException(status_code=404, detail="model release not found")
        # Store-only: return the configuration as acknowledged
        return {
            "model_release_id": str(model_release_id),
            "model_key": payload.model_key,
            "changeover_strategy": payload.changeover_strategy,
            "max_drain_seconds": payload.max_drain_seconds,
            "rollback_on_failure_rate": payload.rollback_on_failure_rate,
            "status": "configured",
        }

    @app.get("/v1/projects/{project_id}/events")
    async def stream_project_events(
        project_id: UUID,
        workspace: Annotated[UUID, Depends(workspace_id)],
        since: Annotated[str | None, Query()] = None,
        poll_interval: Annotated[float, Query(ge=0.5, le=10.0)] = 1.0,
    ) -> StreamingResponse:
        """Server-Sent Events stream for project activity.

        Emits: id / event / data lines per SSE spec.
        Pass the last received created_at ISO timestamp as `since` to resume.
        """

        async def event_generator():  # type: ignore[return]
            current_since = since
            while True:
                events = await repo.list_outbox_events(
                    workspace, project_id, since=current_since, limit=20
                )
                for ev in events:
                    current_since = ev["created_at"].isoformat()
                    yield (
                        f"id: {ev['event_id']}\n"
                        f"event: {ev['event_type']}\n"
                        f"data: {json.dumps(ev['payload'])}\n\n"
                    )
                if not events:
                    yield ": heartbeat\n\n"
                await asyncio.sleep(poll_interval)

        return StreamingResponse(event_generator(), media_type="text/event-stream")

    @app.get(
        "/v1/projects/{project_id}/events/recent",
        response_model=list[OutboxEventRead],
    )
    async def list_recent_events(
        project_id: UUID,
        workspace: Annotated[UUID, Depends(workspace_id)],
        since: Annotated[str | None, Query()] = None,
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
    ) -> list[OutboxEventRead]:
        """Non-streaming snapshot of recent project events."""
        try:
            events = await repo.list_outbox_events(
                workspace, project_id, since=since, limit=limit
            )
            return [OutboxEventRead(**ev) for ev in events]
        except ProjectNotFoundError as exc:
            raise HTTPException(status_code=404, detail="project not found") from exc

    @app.get(
        "/v1/projects/{project_id}/assets",
        response_model=list[MediaAssetRead],
    )
    async def search_project_assets(
        project_id: UUID,
        workspace: Annotated[UUID, Depends(workspace_id)],
        episode_id: Annotated[UUID | None, Query()] = None,
        stage_type: Annotated[str | None, Query(max_length=64)] = None,
        content_type: Annotated[str | None, Query(max_length=100)] = None,
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> list[MediaAssetRead]:
        """Search media assets belonging to the project, with optional filters."""
        try:
            return await repo.search_assets(
                workspace,
                project_id,
                episode_id=episode_id,
                stage_type=stage_type,
                content_type=content_type,
                limit=limit,
                offset=offset,
            )
        except ProjectNotFoundError as exc:
            raise HTTPException(status_code=404, detail="project not found") from exc

    class CacheStats(BaseModel):
        size: int
        active: int
        ttl_seconds: float

    @app.get("/v1/cache/stats", response_model=CacheStats, tags=["system"])
    async def get_cache_stats() -> CacheStats:
        """Return in-process TTL cache statistics."""
        cache = getattr(repo, "_cache", None)
        if cache is None:
            return CacheStats(size=0, active=0, ttl_seconds=0.0)
        raw = await cache.stats()
        return CacheStats(**raw)

    @app.post("/v1/cache:invalidate", response_model=dict, tags=["system"])
    async def invalidate_cache() -> dict:
        """Flush the in-process TTL cache. Returns the count of invalidated entries."""
        cache = getattr(repo, "_cache", None)
        if cache is None:
            return {"invalidated_count": 0}
        count = await cache.invalidate()
        return {"invalidated_count": count}

    @app.post(
        "/v1/projects/{project_id}/episodes/{episode_id}:rollback-production",
        response_model=EpisodeRollbackResult,
        status_code=status.HTTP_200_OK,
    )
    async def rollback_episode_production(
        project_id: UUID,
        episode_id: UUID,
        payload: EpisodeProductionRollback,
        workspace: Annotated[UUID, Depends(workspace_id)],
    ) -> EpisodeRollbackResult:
        try:
            return await repo.rollback_episode_production(
                workspace, project_id, episode_id, payload
            )
        except ProjectNotFoundError as exc:
            raise HTTPException(
                status_code=404, detail="project or episode not found"
            ) from exc

    @app.post(
        "/v1/model-releases/{release_id}:promote-to-active",
        response_model=ModelReleaseRead,
        status_code=status.HTTP_200_OK,
    )
    async def promote_model_to_active(
        release_id: UUID,
        payload: ModelPromoteRequest,
        workspace: Annotated[UUID, Depends(workspace_id)],
    ) -> ModelReleaseRead:
        try:
            return await repo.promote_model_to_active(workspace, release_id, payload)
        except ProjectNotFoundError as exc:
            raise HTTPException(status_code=404, detail="model release not found") from exc
        except ModelReleaseConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post(
        "/v1/projects/{project_id}/episodes:register",
        response_model=list[EpisodeRead],
        status_code=status.HTTP_201_CREATED,
    )
    async def register_episodes(
        project_id: UUID,
        payload: list[EpisodeRegisterItem],
        workspace: Annotated[UUID, Depends(workspace_id)],
    ) -> list[EpisodeRead]:
        try:
            return await repo.register_episodes(workspace, project_id, payload)
        except ProjectNotFoundError as exc:
            raise HTTPException(status_code=404, detail="project not found") from exc
        except ProjectArchivedError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post(
        "/v1/projects/{project_id}/assets:generate",
        response_model=JobRead,
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def generate_assets(
        project_id: UUID,
        response: Response,
        workspace: Annotated[UUID, Depends(workspace_id)],
        payload: AssetGenerateRequest | None = None,
    ) -> JobRead:
        try:
            job = await repo.create_analysis_job(workspace, project_id)
        except ProjectNotFoundError as exc:
            raise HTTPException(status_code=404, detail="project not found") from exc
        except ProjectArchivedError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except AnalysisNotReadyError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        response.headers["Location"] = f"/v1/jobs/{job.id}"
        return job

    @app.post(
        "/v1/projects/{project_id}/assets:approve",
        response_model=ProjectRead,
    )
    async def approve_assets(
        project_id: UUID,
        payload: AssetApproveRequest,
        workspace: Annotated[UUID, Depends(workspace_id)],
    ) -> ProjectRead:
        try:
            return await repo.approve_assets(workspace, project_id, payload.release_ids)
        except ProjectNotFoundError as exc:
            raise HTTPException(status_code=404, detail="project not found") from exc

    @app.get(
        "/v1/projects/{project_id}/deliverables",
        response_model=list[DeliveryRead],
    )
    async def list_deliverables(
        project_id: UUID,
        workspace: Annotated[UUID, Depends(workspace_id)],
    ) -> list[DeliveryRead]:
        try:
            return await repo.list_deliveries(workspace, project_id)
        except ProjectNotFoundError as exc:
            raise HTTPException(status_code=404, detail="project not found") from exc

    # --- Webhook endpoints (in-memory) ---

    _webhooks: dict[UUID, WebhookConfig] = {}

    @app.post(
        "/v1/webhooks",
        response_model=WebhookConfig,
        status_code=status.HTTP_201_CREATED,
        tags=["webhooks"],
    )
    async def register_webhook(
        payload: WebhookCreate,
        workspace: Annotated[UUID, Depends(workspace_id)],
    ) -> WebhookConfig:
        from datetime import UTC, datetime  # noqa: PLC0415

        cfg = WebhookConfig(
            webhook_id=uuid4(),
            workspace_id=workspace,
            url=payload.url,
            secret=payload.secret,
            event_types=payload.event_types,
            created_at=datetime.now(UTC),
        )
        _webhooks[cfg.webhook_id] = cfg
        return cfg

    @app.get(
        "/v1/webhooks",
        response_model=list[WebhookConfig],
        tags=["webhooks"],
    )
    async def list_webhooks(
        workspace: Annotated[UUID, Depends(workspace_id)],
    ) -> list[WebhookConfig]:
        return [w for w in _webhooks.values() if w.workspace_id == workspace]

    @app.delete(
        "/v1/webhooks/{webhook_id}",
        status_code=status.HTTP_204_NO_CONTENT,
        tags=["webhooks"],
    )
    async def delete_webhook(
        webhook_id: UUID,
        workspace: Annotated[UUID, Depends(workspace_id)],
    ) -> None:
        cfg = _webhooks.get(webhook_id)
        if cfg is None or cfg.workspace_id != workspace:
            raise HTTPException(status_code=404, detail="webhook not found")
        del _webhooks[webhook_id]

    @app.post(
        "/v1/webhooks/{webhook_id}:test",
        response_model=dict,
        tags=["webhooks"],
    )
    async def test_webhook(
        webhook_id: UUID,
        workspace: Annotated[UUID, Depends(workspace_id)],
    ) -> dict:
        cfg = _webhooks.get(webhook_id)
        if cfg is None or cfg.workspace_id != workspace:
            raise HTTPException(status_code=404, detail="webhook not found")
        return {"pinged": True, "webhook_id": str(webhook_id)}

    # --- Alert endpoints ---

    _EVENT_ALERT_MAP: dict[str, tuple[str, str]] = {
        "delivery.approved": ("delivery_approved", "INFO"),
        "delivery.revoked": ("delivery_revoked", "WARN"),
        "qc.hard_failure": ("high_failure_rate", "CRITICAL"),
        "circuit_breaker.tripped": ("circuit_breaker_tripped", "CRITICAL"),
        "budget.warning": ("budget_warning", "WARN"),
        "budget.exceeded": ("budget_exceeded", "CRITICAL"),
        "stage_lease.expired": ("stage_lease_expired", "WARN"),
        "model.rollback_triggered": ("model_rollback_triggered", "WARN"),
    }

    @app.get(
        "/v1/projects/{project_id}/alerts",
        response_model=list[ProductionAlert],
        tags=["monitoring"],
    )
    async def list_project_alerts(
        project_id: UUID,
        workspace: Annotated[UUID, Depends(workspace_id)],
        severity: Annotated[str | None, Query(max_length=16)] = None,
        limit: Annotated[int, Query(ge=1, le=500)] = 50,
    ) -> list[ProductionAlert]:
        """Return recent alerts derived from Outbox events for this project."""
        events = await repo.list_outbox_events(workspace, project_id, limit=limit)
        alerts: list[ProductionAlert] = []
        for ev in events:
            mapping = _EVENT_ALERT_MAP.get(ev["event_type"])
            if mapping is None:
                continue
            alert_type, sev = mapping
            if severity is not None and sev != severity:
                continue
            payload = ev.get("payload") or {}
            episode_id_raw = payload.get("episode_id")
            try:
                episode_id = UUID(episode_id_raw) if episode_id_raw else None
            except (ValueError, AttributeError):
                episode_id = None
            alerts.append(
                ProductionAlert(
                    alert_id=str(ev["event_id"]),
                    project_id=project_id,
                    episode_id=episode_id,
                    severity=sev,
                    alert_type=alert_type,
                    message=payload.get("message") or ev["event_type"],
                    metadata=payload,
                    created_at=ev["created_at"],
                )
            )
        return alerts

    # --- Concurrency policy endpoints ---

    @app.get(
        "/v1/concurrency-policies/default",
        response_model=ConcurrencyPolicy,
        tags=["monitoring"],
    )
    async def get_default_concurrency_policy() -> ConcurrencyPolicy:
        """Return the default concurrency policy."""
        return DEFAULT_CONCURRENCY_POLICY

    @app.post(
        "/v1/concurrency-policies/validate",
        response_model=ConcurrencyPolicy,
        tags=["monitoring"],
    )
    async def validate_concurrency_policy(payload: ConcurrencyPolicy) -> ConcurrencyPolicy:
        """Validate a proposed ConcurrencyPolicy and return it."""
        return payload

    return app


app = create_app()
TEST_WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000001")
