from math import ceil
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI, Header, HTTPException, Response, status
from vtv_db.repository import (
    ProjectNotFoundError,
    ProjectRepository,
    UploadConflictError,
)
from vtv_schemas.jobs import JobAccepted, JobRead
from vtv_schemas.projects import ProjectCreate, ProjectRead
from vtv_schemas.uploads import MultipartComplete, MultipartInit, MultipartUpload, UploadRead
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
        status_url = f"/v1/jobs/{job.id}"
        response.headers["Location"] = status_url
        return JobAccepted(job_id=job.id, status=job.status, status_url=status_url)

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
