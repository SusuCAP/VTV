from math import ceil
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Response, status
from fastapi.middleware.cors import CORSMiddleware
from vtv_db.repository import (
    AnalysisNotReadyError,
    ArtifactConflictError,
    ModelReleaseConflictError,
    ProductionNotReadyError,
    ProjectNotFoundError,
    ProjectRepository,
    RightsReleaseConflictError,
    UploadConflictError,
)
from vtv_schemas.analysis import AnalysisDocumentRead
from vtv_schemas.benchmarks import BenchmarkReleaseCreate, BenchmarkReleaseRead
from vtv_schemas.episodes import EpisodeRead
from vtv_schemas.jobs import JobAccepted, JobRead
from vtv_schemas.model_releases import (
    ModelAutomationUpdate,
    ModelLicenseReview,
    ModelReleaseCreate,
    ModelReleaseRead,
)
from vtv_schemas.production import DubbingJobCreate
from vtv_schemas.projects import ProjectCreate, ProjectRead
from vtv_schemas.releases import (
    ArtifactConfirm,
    ArtifactReleaseCreate,
    ArtifactReleaseRead,
    ArtifactTransition,
)
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
from vtv_storage import ObjectStoreAdapter, UploadIntegrityError, UploadNotFoundError

from .config import get_settings
from .database import create_repository
from .storage import create_object_store

DEFAULT_LOCAL_WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000001")


def workspace_id(x_workspace_id: Annotated[UUID | None, Header()] = None) -> UUID:
    return x_workspace_id or DEFAULT_LOCAL_WORKSPACE_ID


def create_app(
    repository: ProjectRepository | None = None,
    object_store: ObjectStoreAdapter | None = None,
) -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.api_title, version=settings.api_version)
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
        allow_headers=["Content-Type", "X-Workspace-Id"],
    )
    repo = repository or create_repository(settings)
    storage = object_store or create_object_store(settings)
    app.state.repository = repo
    app.state.object_store = storage

    @app.get("/healthz", tags=["system"])
    def health() -> dict[str, str]:
        return {"status": "ok", "environment": settings.environment}

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
    ) -> list[ProjectRead]:
        return await repo.list_projects(workspace)

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
        except AnalysisNotReadyError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        status_url = f"/v1/jobs/{job.id}"
        response.headers["Location"] = status_url
        return JobAccepted(job_id=job.id, status=job.status, status_url=status_url)

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
        except ProductionNotReadyError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        status_url = f"/v1/jobs/{job.id}"
        response.headers["Location"] = status_url
        return JobAccepted(job_id=job.id, status=job.status, status_url=status_url)

    @app.get("/v1/projects/{project_id}/episodes", response_model=list[EpisodeRead])
    async def list_episodes(
        project_id: UUID,
        workspace: Annotated[UUID, Depends(workspace_id)],
    ) -> list[EpisodeRead]:
        try:
            return await repo.list_episodes(workspace, project_id)
        except ProjectNotFoundError as exc:
            raise HTTPException(status_code=404, detail="project not found") from exc

    @app.get("/v1/projects/{project_id}/jobs", response_model=list[JobRead])
    async def list_jobs(
        project_id: UUID,
        workspace: Annotated[UUID, Depends(workspace_id)],
    ) -> list[JobRead]:
        try:
            return await repo.list_jobs(workspace, project_id)
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

    return app


app = create_app()
