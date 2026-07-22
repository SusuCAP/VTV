from datetime import UTC, datetime
from threading import RLock
from uuid import UUID, uuid4

from vtv_db.repository import ProjectNotFoundError, UploadConflictError, UploadRecord
from vtv_schemas.enums import JobStatus, ProjectStatus
from vtv_schemas.jobs import JobRead
from vtv_schemas.projects import ProjectCreate, ProjectRead
from vtv_schemas.uploads import MultipartInit, UploadPart, UploadRead


class MemoryRepository:
    """Development repository; PostgreSQL replaces it in the next increment."""

    def __init__(self) -> None:
        self._projects: dict[UUID, ProjectRead] = {}
        self._jobs: dict[UUID, JobRead] = {}
        self._uploads: dict[UUID, UploadRecord] = {}
        self._lock = RLock()

    async def create_project(self, workspace_id: UUID, payload: ProjectCreate) -> ProjectRead:
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

    async def get_project(self, workspace_id: UUID, project_id: UUID) -> ProjectRead:
        with self._lock:
            project = self._projects.get(project_id)
        if project is None or project.workspace_id != workspace_id:
            raise ProjectNotFoundError(project_id)
        return project

    async def create_analysis_job(self, workspace_id: UUID, project_id: UUID) -> JobRead:
        project = await self.get_project(workspace_id, project_id)
        job = JobRead(
            id=uuid4(),
            project_id=project.id,
            kind="PROJECT_ANALYSIS",
            status=JobStatus.QUEUED,
            progress=0,
            total_stages=6,
            completed_stages=0,
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

    async def get_job(self, workspace_id: UUID, job_id: UUID) -> JobRead:
        with self._lock:
            job = self._jobs.get(job_id)
        if job is None:
            raise ProjectNotFoundError(job_id)
        await self.get_project(workspace_id, job.project_id)
        return job

    async def create_upload_session(
        self,
        workspace_id: UUID,
        upload_id: UUID,
        payload: MultipartInit,
        object_key: str,
        provider_upload_id: str,
    ) -> UploadRead:
        await self.get_project(workspace_id, payload.project_id)
        upload = UploadRead(
            upload_id=upload_id,
            project_id=payload.project_id,
            object_key=object_key,
            size_bytes=payload.size_bytes,
            status="UPLOADING",
        )
        record = UploadRecord(
            upload=upload,
            provider_upload_id=provider_upload_id,
            declared_sha256=payload.sha256,
            content_type=payload.content_type,
            part_size_bytes=payload.part_size_bytes,
        )
        with self._lock:
            self._uploads[upload_id] = record
        return upload

    async def get_upload(self, workspace_id: UUID, upload_id: UUID) -> UploadRecord:
        with self._lock:
            record = self._uploads.get(upload_id)
        if record is None:
            raise ProjectNotFoundError(upload_id)
        await self.get_project(workspace_id, record.upload.project_id)
        return record

    async def complete_upload(
        self,
        workspace_id: UUID,
        upload_id: UUID,
        parts: list[UploadPart],
        object_checksum_sha256: str,
        object_uri: str,
        content_type: str,
        size_bytes: int,
    ) -> UploadRead:
        record = await self.get_upload(workspace_id, upload_id)
        if record.upload.status != "UPLOADING":
            raise UploadConflictError(f"upload is already {record.upload.status}")
        if record.declared_sha256 != object_checksum_sha256:
            raise UploadConflictError("object SHA-256 does not match upload declaration")
        if record.upload.size_bytes != size_bytes:
            raise UploadConflictError("stored object size does not match upload declaration")
        completed = record.upload.model_copy(
            update={
                "status": "COMPLETED",
                "completed_parts": parts,
                "episode_id": uuid4(),
                "media_asset_id": uuid4(),
                "ingest_job_id": uuid4(),
            }
        )
        with self._lock:
            self._uploads[upload_id] = UploadRecord(
                upload=completed,
                provider_upload_id=record.provider_upload_id,
                declared_sha256=record.declared_sha256,
                content_type=content_type,
                part_size_bytes=record.part_size_bytes,
            )
        return completed

    async def register_orphan_asset(
        self,
        workspace_id: UUID,
        project_id: UUID,
        object_uri: str,
        reason: str,
    ) -> None:
        await self.get_project(workspace_id, project_id)
