from typing import Annotated
from uuid import UUID

from fastapi import Depends, FastAPI, Header, HTTPException, Response, status
from vtv_db.repository import ProjectNotFoundError, ProjectRepository
from vtv_schemas.jobs import JobAccepted, JobRead
from vtv_schemas.projects import ProjectCreate, ProjectRead
from vtv_schemas.uploads import MultipartComplete, MultipartInit, MultipartUpload, UploadRead
from vtv_storage import MemoryObjectStore, UploadIntegrityError
from vtv_storage.adapter import UploadNotFoundError

from .config import get_settings
from .database import create_repository

DEFAULT_LOCAL_WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000001")


def workspace_id(x_workspace_id: Annotated[UUID | None, Header()] = None) -> UUID:
    return x_workspace_id or DEFAULT_LOCAL_WORKSPACE_ID


def create_app(
    repository: ProjectRepository | None = None,
    object_store: MemoryObjectStore | None = None,
) -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.api_title, version=settings.api_version)
    repo = repository or create_repository(settings)
    storage = object_store or MemoryObjectStore()
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
        try:
            await repo.get_project(workspace, payload.project_id)
        except ProjectNotFoundError as exc:
            raise HTTPException(status_code=404, detail="project not found") from exc
        return storage.multipart_init(workspace, payload)

    @app.post("/v1/uploads/{upload_id}/multipart-complete", response_model=UploadRead)
    def multipart_complete(
        upload_id: UUID,
        payload: MultipartComplete,
        workspace: Annotated[UUID, Depends(workspace_id)],
    ) -> UploadRead:
        try:
            return storage.multipart_complete(workspace, upload_id, payload)
        except UploadNotFoundError as exc:
            raise HTTPException(status_code=404, detail="upload not found") from exc
        except UploadIntegrityError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/v1/uploads/{upload_id}", response_model=UploadRead)
    def get_upload(
        upload_id: UUID,
        workspace: Annotated[UUID, Depends(workspace_id)],
    ) -> UploadRead:
        try:
            return storage.get_upload(workspace, upload_id)
        except UploadNotFoundError as exc:
            raise HTTPException(status_code=404, detail="upload not found") from exc

    return app


app = create_app()
