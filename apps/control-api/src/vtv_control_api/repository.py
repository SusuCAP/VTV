from datetime import UTC, datetime
from threading import RLock
from uuid import UUID, uuid4

from vtv_schemas.enums import JobStatus, ProjectStatus
from vtv_schemas.jobs import JobRead
from vtv_schemas.projects import ProjectCreate, ProjectRead


class ProjectNotFoundError(KeyError):
    pass


class MemoryRepository:
    """Development repository; PostgreSQL replaces it in the next increment."""

    def __init__(self) -> None:
        self._projects: dict[UUID, ProjectRead] = {}
        self._jobs: dict[UUID, JobRead] = {}
        self._lock = RLock()

    def create_project(self, workspace_id: UUID, payload: ProjectCreate) -> ProjectRead:
        now = datetime.now(UTC)
        project = ProjectRead(
            **payload.model_dump(),
            id=uuid4(),
            workspace_id=workspace_id,
            status=ProjectStatus.DRAFT,
            state_version=1,
            created_at=now,
            updated_at=now,
        )
        with self._lock:
            self._projects[project.id] = project
        return project

    def get_project(self, workspace_id: UUID, project_id: UUID) -> ProjectRead:
        with self._lock:
            project = self._projects.get(project_id)
        if project is None or project.workspace_id != workspace_id:
            raise ProjectNotFoundError(project_id)
        return project

    def create_analysis_job(self, workspace_id: UUID, project_id: UUID) -> JobRead:
        project = self.get_project(workspace_id, project_id)
        job = JobRead(
            id=uuid4(),
            project_id=project.id,
            kind="PROJECT_ANALYSIS",
            status=JobStatus.QUEUED,
            progress=0,
        )
        with self._lock:
            self._jobs[job.id] = job
            self._projects[project.id] = project.model_copy(
                update={
                    "status": ProjectStatus.ANALYZING,
                    "state_version": project.state_version + 1,
                    "updated_at": datetime.now(UTC),
                }
            )
        return job

    def get_job(self, workspace_id: UUID, job_id: UUID) -> JobRead:
        with self._lock:
            job = self._jobs.get(job_id)
        if job is None:
            raise ProjectNotFoundError(job_id)
        self.get_project(workspace_id, job.project_id)
        return job
