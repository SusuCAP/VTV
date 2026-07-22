from datetime import UTC, datetime
from threading import RLock
from uuid import UUID, uuid4

from vtv_db.model_registry import (
    AutomationStatus,
    InvalidModelReleaseTransitionError,
    LicenseStatus,
    ModelReleaseState,
    review_license,
    set_automation_status,
)
from vtv_db.releases import (
    ArtifactReleaseState,
    ArtifactReleaseStatus,
    InvalidArtifactTransitionError,
    confirm_release,
    publish_release,
)
from vtv_db.repository import (
    AnalysisNotReadyError,
    ArtifactConflictError,
    ModelReleaseConflictError,
    ProjectNotFoundError,
    UploadConflictError,
    UploadRecord,
)
from vtv_schemas.analysis import AnalysisDocumentRead
from vtv_schemas.enums import JobStatus, ProjectStatus
from vtv_schemas.episodes import EpisodeRead
from vtv_schemas.jobs import JobRead
from vtv_schemas.model_releases import ModelReleaseCreate, ModelReleaseRead
from vtv_schemas.projects import ProjectCreate, ProjectRead
from vtv_schemas.releases import ArtifactReleaseCreate, ArtifactReleaseRead
from vtv_schemas.uploads import MultipartInit, UploadPart, UploadRead


class MemoryRepository:
    """Development repository; PostgreSQL replaces it in the next increment."""

    def __init__(self) -> None:
        self._projects: dict[UUID, ProjectRead] = {}
        self._jobs: dict[UUID, JobRead] = {}
        self._uploads: dict[UUID, UploadRecord] = {}
        self._episodes: dict[UUID, list[EpisodeRead]] = {}
        self._releases: dict[UUID, ArtifactReleaseRead] = {}
        self._analysis_documents: list[AnalysisDocumentRead] = []
        self._model_releases: dict[UUID, ModelReleaseRead] = {}
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

    async def create_model_release(
        self, workspace_id: UUID, payload: ModelReleaseCreate
    ) -> ModelReleaseRead:
        with self._lock:
            if any(
                item.workspace_id == workspace_id
                and item.model_key == payload.model_key
                and item.release_name == payload.release_name
                for item in self._model_releases.values()
            ):
                raise ModelReleaseConflictError("model release already exists")
            if payload.fallback_release_id:
                fallback = self._model_releases.get(payload.fallback_release_id)
                if (
                    fallback is None
                    or fallback.workspace_id != workspace_id
                    or fallback.model_key != payload.model_key
                ):
                    raise ProjectNotFoundError(payload.fallback_release_id)
            now = datetime.now(UTC)
            release = ModelReleaseRead(
                id=uuid4(),
                workspace_id=workspace_id,
                model_key=payload.model_key,
                release_name=payload.release_name,
                provider=payload.provider,
                endpoint=payload.endpoint,
                license_id=payload.license_id,
                license_status="REVIEW",
                automation_status="OBSERVE",
                traffic_percent=0,
                state_version=1,
                model_card_uri=payload.model_card_uri,
                config=payload.config,
                fallback_release_id=payload.fallback_release_id,
                created_at=now,
                updated_at=now,
            )
            self._model_releases[release.id] = release
            return release

    async def list_model_releases(
        self, workspace_id: UUID, model_key: str | None = None
    ) -> list[ModelReleaseRead]:
        with self._lock:
            return [
                item
                for item in self._model_releases.values()
                if item.workspace_id == workspace_id
                and (model_key is None or item.model_key == model_key)
            ]

    async def review_model_license(
        self,
        workspace_id: UUID,
        release_id: UUID,
        decision: str,
        actor_id: UUID,
        expected_state_version: int,
    ) -> ModelReleaseRead:
        release = self._get_model_release(workspace_id, release_id)
        try:
            state = review_license(
                _memory_model_state(release),
                decision=LicenseStatus(decision),
                actor_id=actor_id,
                expected_state_version=expected_state_version,
            )
        except InvalidModelReleaseTransitionError as exc:
            raise ModelReleaseConflictError(str(exc)) from exc
        return self._store_model_state(release, state)

    async def update_model_automation(
        self,
        workspace_id: UUID,
        release_id: UUID,
        target: str,
        traffic_percent: int,
        expected_state_version: int,
    ) -> ModelReleaseRead:
        release = self._get_model_release(workspace_id, release_id)
        target_status = AutomationStatus(target)
        with self._lock:
            others = [
                item
                for item in self._model_releases.values()
                if item.id != release.id
                and item.workspace_id == workspace_id
                and item.model_key == release.model_key
                and item.automation_status in {"CANARY", "ACTIVE"}
            ]
            active = [item for item in others if item.automation_status == "ACTIVE"]
            canary = [item for item in others if item.automation_status == "CANARY"]
            if target_status is AutomationStatus.CANARY and (canary or not active):
                raise ModelReleaseConflictError(
                    "canary requires one ACTIVE baseline and no other canary"
                )
            if target_status is AutomationStatus.ACTIVE:
                if canary:
                    raise ModelReleaseConflictError("another canary release must be disabled")
                if active and release.automation_status != "CANARY":
                    raise ModelReleaseConflictError("activate through canary first")
                if active:
                    previous = active[0]
                    disabled = set_automation_status(
                        _memory_model_state(previous),
                        target=AutomationStatus.DISABLED,
                        traffic_percent=0,
                        expected_state_version=previous.state_version,
                    )
                    self._store_model_state(previous, disabled)
        try:
            state = set_automation_status(
                _memory_model_state(release),
                target=target_status,
                traffic_percent=traffic_percent,
                expected_state_version=expected_state_version,
            )
        except InvalidModelReleaseTransitionError as exc:
            raise ModelReleaseConflictError(str(exc)) from exc
        return self._store_model_state(release, state)

    def _get_model_release(self, workspace_id: UUID, release_id: UUID) -> ModelReleaseRead:
        with self._lock:
            release = self._model_releases.get(release_id)
        if release is None or release.workspace_id != workspace_id:
            raise ProjectNotFoundError(release_id)
        return release

    def _store_model_state(
        self, release: ModelReleaseRead, state: ModelReleaseState
    ) -> ModelReleaseRead:
        changed = release.model_copy(
            update={
                "license_status": state.license_status,
                "automation_status": state.automation_status,
                "traffic_percent": state.traffic_percent,
                "state_version": state.state_version,
                "reviewed_by": state.reviewed_by,
                "reviewed_at": state.reviewed_at,
                "updated_at": datetime.now(UTC),
            }
        )
        with self._lock:
            self._model_releases[release.id] = changed
        return changed

    async def get_project(self, workspace_id: UUID, project_id: UUID) -> ProjectRead:
        with self._lock:
            project = self._projects.get(project_id)
        if project is None or project.workspace_id != workspace_id:
            raise ProjectNotFoundError(project_id)
        return project

    async def list_projects(self, workspace_id: UUID) -> list[ProjectRead]:
        with self._lock:
            return [
                project
                for project in self._projects.values()
                if project.workspace_id == workspace_id
            ]

    async def list_episodes(
        self, workspace_id: UUID, project_id: UUID
    ) -> list[EpisodeRead]:
        await self.get_project(workspace_id, project_id)
        with self._lock:
            return list(self._episodes.get(project_id, []))

    async def list_jobs(self, workspace_id: UUID, project_id: UUID) -> list[JobRead]:
        await self.get_project(workspace_id, project_id)
        with self._lock:
            return [job for job in self._jobs.values() if job.project_id == project_id]

    async def create_analysis_job(self, workspace_id: UUID, project_id: UUID) -> JobRead:
        project = await self.get_project(workspace_id, project_id)
        with self._lock:
            episodes = list(self._episodes.get(project_id, []))
        if not episodes:
            raise AnalysisNotReadyError("project analysis requires an uploaded episode")
        job = JobRead(
            id=uuid4(),
            project_id=project.id,
            kind="PROJECT_ANALYSIS",
            status=JobStatus.QUEUED,
            progress=0,
            total_stages=len(episodes) * 5 + 1,
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

    async def create_artifact_release(
        self, workspace_id: UUID, project_id: UUID, payload: ArtifactReleaseCreate
    ) -> ArtifactReleaseRead:
        await self.get_project(workspace_id, project_id)
        with self._lock:
            dependencies = set(payload.dependency_release_ids)
            if any(
                release_id not in self._releases
                or self._releases[release_id].project_id != project_id
                for release_id in dependencies
            ):
                raise ProjectNotFoundError("artifact dependency")
            if payload.supersedes_release_id:
                superseded = self._releases.get(payload.supersedes_release_id)
                if (
                    superseded is None
                    or superseded.project_id != project_id
                    or superseded.artifact_type != payload.artifact_type
                ):
                    raise ArtifactConflictError(
                        "superseded release must have the same artifact type"
                    )
            version = 1 + max(
                (
                    item.version
                    for item in self._releases.values()
                    if item.project_id == project_id and item.artifact_type == payload.artifact_type
                ),
                default=0,
            )
            now = datetime.now(UTC)
            release = ArtifactReleaseRead(
                id=uuid4(),
                project_id=project_id,
                artifact_type=payload.artifact_type,
                version=version,
                status="DRAFT",
                state_version=1,
                content_asset_id=payload.content_asset_id,
                supersedes_release_id=payload.supersedes_release_id,
                dependency_release_ids=tuple(sorted(dependencies)),
                created_at=now,
                updated_at=now,
            )
            self._releases[release.id] = release
            if payload.supersedes_release_id:
                self._invalidate_memory_graph(payload.supersedes_release_id)
            return release

    async def list_artifact_releases(
        self, workspace_id: UUID, project_id: UUID
    ) -> list[ArtifactReleaseRead]:
        await self.get_project(workspace_id, project_id)
        with self._lock:
            return [item for item in self._releases.values() if item.project_id == project_id]

    async def list_analysis_documents(
        self,
        workspace_id: UUID,
        project_id: UUID,
        episode_id: UUID | None = None,
        document_type: str | None = None,
    ) -> list[AnalysisDocumentRead]:
        await self.get_project(workspace_id, project_id)
        with self._lock:
            return [
                item
                for item in self._analysis_documents
                if item.project_id == project_id
                and (episode_id is None or item.episode_id == episode_id)
                and (document_type is None or item.document_type == document_type)
            ]

    async def confirm_artifact_release(
        self, workspace_id: UUID, release_id: UUID, actor_id: UUID, expected_state_version: int
    ) -> ArtifactReleaseRead:
        release = await self._get_release(workspace_id, release_id)
        try:
            changed = confirm_release(
                _memory_state(release),
                actor_id=actor_id,
                expected_state_version=expected_state_version,
            )
        except InvalidArtifactTransitionError as exc:
            raise ArtifactConflictError(str(exc)) from exc
        return self._store_release_state(release, changed)

    async def publish_artifact_release(
        self, workspace_id: UUID, release_id: UUID, expected_state_version: int
    ) -> ArtifactReleaseRead:
        release = await self._get_release(workspace_id, release_id)
        with self._lock:
            dependencies = tuple(
                _memory_state(self._releases[item]) for item in release.dependency_release_ids
            )
        try:
            changed = publish_release(
                _memory_state(release),
                dependencies=dependencies,
                expected_state_version=expected_state_version,
            )
        except InvalidArtifactTransitionError as exc:
            raise ArtifactConflictError(str(exc)) from exc
        return self._store_release_state(release, changed)

    async def invalidate_artifact_release(
        self, workspace_id: UUID, release_id: UUID, expected_state_version: int
    ) -> list[ArtifactReleaseRead]:
        root = await self._get_release(workspace_id, release_id)
        if root.state_version != expected_state_version:
            raise ArtifactConflictError("artifact state version mismatch")
        with self._lock:
            pending = [root.id]
            visited: set[UUID] = set()
            changed: list[ArtifactReleaseRead] = []
            while pending:
                current_id = pending.pop()
                if current_id in visited:
                    continue
                visited.add(current_id)
                current = self._releases[current_id]
                if current.status != "STALE":
                    current = current.model_copy(
                        update={
                            "status": "STALE",
                            "state_version": current.state_version + 1,
                            "stale_at": datetime.now(UTC),
                            "updated_at": datetime.now(UTC),
                        }
                    )
                    self._releases[current.id] = current
                    changed.append(current)
                pending.extend(
                    item.id
                    for item in self._releases.values()
                    if current_id in item.dependency_release_ids
                )
            return changed

    async def _get_release(
        self, workspace_id: UUID, release_id: UUID
    ) -> ArtifactReleaseRead:
        with self._lock:
            release = self._releases.get(release_id)
        if release is None:
            raise ProjectNotFoundError(release_id)
        await self.get_project(workspace_id, release.project_id)
        return release

    def _store_release_state(
        self, release: ArtifactReleaseRead, state: ArtifactReleaseState
    ) -> ArtifactReleaseRead:
        changed = release.model_copy(
            update={
                "status": state.status,
                "state_version": state.state_version,
                "confirmed_by": state.confirmed_by,
                "confirmed_at": state.confirmed_at,
                "released_at": state.released_at,
                "stale_at": state.stale_at,
                "updated_at": datetime.now(UTC),
            }
        )
        with self._lock:
            self._releases[release.id] = changed
        return changed

    def _invalidate_memory_graph(self, root_release_id: UUID) -> list[ArtifactReleaseRead]:
        pending = [root_release_id]
        visited: set[UUID] = set()
        changed: list[ArtifactReleaseRead] = []
        now = datetime.now(UTC)
        while pending:
            current_id = pending.pop()
            if current_id in visited:
                continue
            visited.add(current_id)
            current = self._releases[current_id]
            if current.status != "STALE":
                current = current.model_copy(
                    update={
                        "status": "STALE",
                        "state_version": current.state_version + 1,
                        "stale_at": now,
                        "updated_at": now,
                    }
                )
                self._releases[current.id] = current
                changed.append(current)
            pending.extend(
                item.id
                for item in self._releases.values()
                if current_id in item.dependency_release_ids
            )
        return changed

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
            filename=payload.filename,
            episode_no=payload.episode_no,
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

    async def find_active_upload(
        self,
        workspace_id: UUID,
        project_id: UUID,
        sha256: str,
    ) -> UploadRecord | None:
        await self.get_project(workspace_id, project_id)
        with self._lock:
            matches = [
                record
                for record in self._uploads.values()
                if record.upload.project_id == project_id
                and record.declared_sha256 == sha256
                and record.upload.status == "UPLOADING"
            ]
        return matches[-1] if matches else None

    async def record_upload_part(
        self,
        workspace_id: UUID,
        upload_id: UUID,
        part: UploadPart,
    ) -> UploadRead:
        record = await self.get_upload(workspace_id, upload_id)
        if record.upload.status != "UPLOADING":
            raise UploadConflictError(f"upload is already {record.upload.status}")
        if part.size_bytes > record.part_size_bytes:
            raise UploadConflictError("part exceeds declared part size")
        completed = {item.part_number: item for item in record.upload.completed_parts}
        completed[part.part_number] = part
        upload = record.upload.model_copy(
            update={"completed_parts": [completed[number] for number in sorted(completed)]}
        )
        with self._lock:
            self._uploads[upload_id] = UploadRecord(
                upload=upload,
                provider_upload_id=record.provider_upload_id,
                declared_sha256=record.declared_sha256,
                content_type=record.content_type,
                part_size_bytes=record.part_size_bytes,
                filename=record.filename,
                episode_no=record.episode_no,
            )
        return upload

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
        episode_id = uuid4()
        media_asset_id = uuid4()
        ingest_job_id = uuid4()
        completed = record.upload.model_copy(
            update={
                "status": "COMPLETED",
                "completed_parts": parts,
                "episode_id": episode_id,
                "media_asset_id": media_asset_id,
                "ingest_job_id": ingest_job_id,
            }
        )
        with self._lock:
            self._uploads[upload_id] = UploadRecord(
                upload=completed,
                provider_upload_id=record.provider_upload_id,
                declared_sha256=record.declared_sha256,
                content_type=content_type,
                part_size_bytes=record.part_size_bytes,
                filename=record.filename,
                episode_no=record.episode_no,
            )
            episodes = self._episodes.setdefault(record.upload.project_id, [])
            episode_no = record.episode_no or len(episodes) + 1
            episodes.append(
                EpisodeRead(
                    id=episode_id,
                    project_id=record.upload.project_id,
                    episode_no=episode_no,
                    title=record.filename,
                    processing_status="QUEUED",
                    source_asset_id=media_asset_id,
                )
            )
            self._jobs[ingest_job_id] = JobRead(
                id=ingest_job_id,
                project_id=record.upload.project_id,
                kind="EPISODE_INGEST",
                status=JobStatus.QUEUED,
                progress=0,
                total_stages=8,
                completed_stages=0,
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


def _memory_state(release: ArtifactReleaseRead) -> ArtifactReleaseState:
    return ArtifactReleaseState(
        release_id=release.id,
        status=ArtifactReleaseStatus(release.status),
        state_version=release.state_version,
        confirmed_by=release.confirmed_by,
        confirmed_at=release.confirmed_at,
        released_at=release.released_at,
        stale_at=release.stale_at,
    )


def _memory_model_state(release: ModelReleaseRead) -> ModelReleaseState:
    return ModelReleaseState(
        release_id=release.id,
        endpoint=release.endpoint,
        license_id=release.license_id,
        model_card_uri=release.model_card_uri,
        license_status=LicenseStatus(release.license_status),
        automation_status=AutomationStatus(release.automation_status),
        traffic_percent=release.traffic_percent,
        state_version=release.state_version,
        reviewed_by=release.reviewed_by,
        reviewed_at=release.reviewed_at,
        approved_benchmark_release_id=release.approved_benchmark_release_id,
    )
