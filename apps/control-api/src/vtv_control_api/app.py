from typing import Annotated
from uuid import UUID

from fastapi import Depends, FastAPI, Header, HTTPException, Response, status
from vtv_schemas.jobs import JobAccepted, JobRead
from vtv_schemas.projects import ProjectCreate, ProjectRead

from .config import get_settings
from .repository import MemoryRepository, ProjectNotFoundError

DEFAULT_LOCAL_WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000001")


def workspace_id(x_workspace_id: Annotated[UUID | None, Header()] = None) -> UUID:
    return x_workspace_id or DEFAULT_LOCAL_WORKSPACE_ID


def create_app(repository: MemoryRepository | None = None) -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.api_title, version=settings.api_version)
    repo = repository or MemoryRepository()
    app.state.repository = repo

    @app.get("/healthz", tags=["system"])
    def health() -> dict[str, str]:
        return {"status": "ok", "environment": settings.environment}

    @app.post("/v1/projects", response_model=ProjectRead, status_code=status.HTTP_201_CREATED)
    def create_project(
        payload: ProjectCreate,
        workspace: Annotated[UUID, Depends(workspace_id)],
    ) -> ProjectRead:
        return repo.create_project(workspace, payload)

    @app.get("/v1/projects/{project_id}", response_model=ProjectRead)
    def get_project(
        project_id: UUID,
        workspace: Annotated[UUID, Depends(workspace_id)],
    ) -> ProjectRead:
        try:
            return repo.get_project(workspace, project_id)
        except ProjectNotFoundError as exc:
            raise HTTPException(status_code=404, detail="project not found") from exc

    @app.post(
        "/v1/projects/{project_id}/analysis-jobs",
        response_model=JobAccepted,
        status_code=status.HTTP_202_ACCEPTED,
    )
    def create_analysis_job(
        project_id: UUID,
        response: Response,
        workspace: Annotated[UUID, Depends(workspace_id)],
    ) -> JobAccepted:
        try:
            job = repo.create_analysis_job(workspace, project_id)
        except ProjectNotFoundError as exc:
            raise HTTPException(status_code=404, detail="project not found") from exc
        status_url = f"/v1/jobs/{job.id}"
        response.headers["Location"] = status_url
        return JobAccepted(job_id=job.id, status=job.status, status_url=status_url)

    @app.get("/v1/jobs/{job_id}", response_model=JobRead)
    def get_job(
        job_id: UUID,
        workspace: Annotated[UUID, Depends(workspace_id)],
    ) -> JobRead:
        try:
            return repo.get_job(workspace, job_id)
        except ProjectNotFoundError as exc:
            raise HTTPException(status_code=404, detail="job not found") from exc

    return app


app = create_app()
