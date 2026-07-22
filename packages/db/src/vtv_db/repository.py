from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Protocol
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from vtv_schemas.enums import JobStatus, ProjectStatus
from vtv_schemas.episodes import EpisodeRead
from vtv_schemas.jobs import JobRead
from vtv_schemas.projects import ProjectCreate, ProjectRead
from vtv_schemas.releases import ArtifactReleaseCreate, ArtifactReleaseRead
from vtv_schemas.uploads import MultipartInit, UploadPart, UploadRead

from .dag import EPISODE_BASELINE_DAG, build_project_analysis_dag
from .models import (
    ArtifactRelease,
    ArtifactReleaseDependency,
    Episode,
    ExecutionControl,
    Job,
    MediaAsset,
    OrphanAsset,
    OutboxEvent,
    Project,
    StageDependency,
    StageRun,
    UploadSession,
    Workspace,
)
from .releases import (
    ArtifactReleaseState,
    ArtifactReleaseStatus,
    InvalidArtifactTransitionError,
    confirm_release,
    publish_release,
)


class ProjectNotFoundError(KeyError):
    pass


class UploadConflictError(ValueError):
    pass


class AnalysisNotReadyError(ValueError):
    pass


class ArtifactConflictError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class UploadRecord:
    upload: UploadRead
    provider_upload_id: str
    declared_sha256: str
    content_type: str
    part_size_bytes: int
    filename: str
    episode_no: int | None


class ProjectRepository(Protocol):
    async def create_project(self, workspace_id: UUID, payload: ProjectCreate) -> ProjectRead: ...

    async def get_project(self, workspace_id: UUID, project_id: UUID) -> ProjectRead: ...

    async def list_projects(self, workspace_id: UUID) -> list[ProjectRead]: ...

    async def list_episodes(self, workspace_id: UUID, project_id: UUID) -> list[EpisodeRead]: ...

    async def list_jobs(self, workspace_id: UUID, project_id: UUID) -> list[JobRead]: ...

    async def create_analysis_job(self, workspace_id: UUID, project_id: UUID) -> JobRead: ...

    async def get_job(self, workspace_id: UUID, job_id: UUID) -> JobRead: ...

    async def create_artifact_release(
        self, workspace_id: UUID, project_id: UUID, payload: ArtifactReleaseCreate
    ) -> ArtifactReleaseRead: ...

    async def list_artifact_releases(
        self, workspace_id: UUID, project_id: UUID
    ) -> list[ArtifactReleaseRead]: ...

    async def confirm_artifact_release(
        self, workspace_id: UUID, release_id: UUID, actor_id: UUID, expected_state_version: int
    ) -> ArtifactReleaseRead: ...

    async def publish_artifact_release(
        self, workspace_id: UUID, release_id: UUID, expected_state_version: int
    ) -> ArtifactReleaseRead: ...

    async def invalidate_artifact_release(
        self, workspace_id: UUID, release_id: UUID, expected_state_version: int
    ) -> list[ArtifactReleaseRead]: ...

    async def create_upload_session(
        self,
        workspace_id: UUID,
        upload_id: UUID,
        payload: MultipartInit,
        object_key: str,
        provider_upload_id: str,
    ) -> UploadRead: ...

    async def get_upload(self, workspace_id: UUID, upload_id: UUID) -> UploadRecord: ...

    async def find_active_upload(
        self,
        workspace_id: UUID,
        project_id: UUID,
        sha256: str,
    ) -> UploadRecord | None: ...

    async def record_upload_part(
        self,
        workspace_id: UUID,
        upload_id: UUID,
        part: UploadPart,
    ) -> UploadRead: ...

    async def complete_upload(
        self,
        workspace_id: UUID,
        upload_id: UUID,
        parts: list[UploadPart],
        object_checksum_sha256: str,
        object_uri: str,
        content_type: str,
        size_bytes: int,
    ) -> UploadRead: ...

    async def register_orphan_asset(
        self,
        workspace_id: UUID,
        project_id: UUID,
        object_uri: str,
        reason: str,
    ) -> None: ...


class SqlAlchemyProjectRepository:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        id_factory: Callable[[], UUID] = uuid4,
    ) -> None:
        self._sessions = session_factory
        self._id_factory = id_factory

    async def create_project(self, workspace_id: UUID, payload: ProjectCreate) -> ProjectRead:
        async with self._sessions.begin() as session:
            await session.execute(
                insert(Workspace)
                .values(id=workspace_id, name=f"Workspace {workspace_id}")
                .on_conflict_do_nothing(index_elements=[Workspace.id])
            )
            project = Project(
                id=self._id_factory(),
                workspace_id=workspace_id,
                name=payload.name,
                target_market=payload.target_market,
                locale=payload.locale,
                timezone=payload.timezone,
                quality_profile=payload.quality_profile,
                status=ProjectStatus.DRAFT,
                state_version=1,
                budget_currency=payload.budget.currency,
                budget_warning_at=payload.budget.warning_at,
                budget_hard_limit=payload.budget.hard_limit,
                output_spec=payload.output.model_dump(mode="json"),
            )
            session.add(project)
            session.add(ExecutionControl(project_id=project.id))
            session.add(
                OutboxEvent(
                    workspace_id=workspace_id,
                    aggregate_type="project",
                    aggregate_id=project.id,
                    event_type="project.created",
                    payload={"project_id": str(project.id)},
                )
            )
            await session.flush()
            return _project_read(project)

    async def get_project(self, workspace_id: UUID, project_id: UUID) -> ProjectRead:
        async with self._sessions() as session:
            project = await session.scalar(
                select(Project).where(
                    Project.id == project_id,
                    Project.workspace_id == workspace_id,
                )
            )
            if project is None:
                raise ProjectNotFoundError(project_id)
            return _project_read(project)

    async def list_projects(self, workspace_id: UUID) -> list[ProjectRead]:
        async with self._sessions() as session:
            projects = list(
                await session.scalars(
                    select(Project)
                    .where(Project.workspace_id == workspace_id)
                    .order_by(Project.updated_at.desc())
                )
            )
            return [_project_read(project) for project in projects]

    async def list_episodes(
        self, workspace_id: UUID, project_id: UUID
    ) -> list[EpisodeRead]:
        async with self._sessions() as session:
            project_exists = await session.scalar(
                select(Project.id).where(
                    Project.id == project_id,
                    Project.workspace_id == workspace_id,
                )
            )
            if project_exists is None:
                raise ProjectNotFoundError(project_id)
            episodes = list(
                await session.scalars(
                    select(Episode)
                    .where(Episode.project_id == project_id)
                    .order_by(Episode.episode_no)
                )
            )
            result: list[EpisodeRead] = []
            for episode in episodes:
                status = await session.scalar(
                    select(Job.status)
                    .join(StageRun, StageRun.job_id == Job.id)
                    .where(StageRun.episode_id == episode.id)
                    .order_by(Job.created_at.desc())
                    .limit(1)
                )
                result.append(
                    EpisodeRead(
                        id=episode.id,
                        project_id=project_id,
                        episode_no=episode.episode_no,
                        title=episode.title,
                        duration_ms=episode.duration_ms,
                        processing_status=status or "READY",
                        source_asset_id=episode.source_asset_id,
                    )
                )
            return result

    async def list_jobs(self, workspace_id: UUID, project_id: UUID) -> list[JobRead]:
        async with self._sessions() as session:
            project_exists = await session.scalar(
                select(Project.id).where(
                    Project.id == project_id,
                    Project.workspace_id == workspace_id,
                )
            )
            if project_exists is None:
                raise ProjectNotFoundError(project_id)
            jobs = list(
                await session.scalars(
                    select(Job).where(Job.project_id == project_id).order_by(Job.created_at.desc())
                )
            )
            return [_job_read(job) for job in jobs]

    async def create_analysis_job(self, workspace_id: UUID, project_id: UUID) -> JobRead:
        async with self._sessions.begin() as session:
            project = await session.scalar(
                select(Project)
                .where(Project.id == project_id, Project.workspace_id == workspace_id)
                .with_for_update()
            )
            if project is None:
                raise ProjectNotFoundError(project_id)
            control = await session.get(ExecutionControl, project_id)
            if control is None:
                raise RuntimeError("project execution control is missing")
            episodes = list(
                await session.scalars(
                    select(Episode)
                    .where(Episode.project_id == project_id, Episode.source_asset_id.is_not(None))
                    .order_by(Episode.episode_no)
                    .with_for_update()
                )
            )
            if not episodes:
                raise AnalysisNotReadyError("project analysis requires an uploaded episode")
            definitions = build_project_analysis_dag(tuple(episode.id for episode in episodes))
            episode_by_id = {episode.id: episode for episode in episodes}
            job = Job(
                id=self._id_factory(),
                project_id=project_id,
                kind="PROJECT_ANALYSIS",
                status=JobStatus.QUEUED,
                idempotency_key=f"project-analysis:{project.state_version}",
                total_stages=len(definitions),
            )
            session.add(job)
            runs: dict[str, StageRun] = {}
            for definition in definitions:
                episode = episode_by_id.get(definition.episode_id)
                params = {
                    "source_locale": "zh-CN",
                    "target_locale": project.locale,
                }
                if episode is not None:
                    params.update(
                        {
                            "episode_id": str(episode.id),
                            "source_asset_id": str(episode.source_asset_id),
                        }
                    )
                run = StageRun(
                    id=self._id_factory(),
                    job_id=job.id,
                    project_id=project_id,
                    episode_id=definition.episode_id,
                    stage_type=definition.stage_type,
                    status="READY" if not definition.depends_on else "PENDING",
                    idempotency_key=f"{job.id}:{definition.key}",
                    runtime_profile_id=definition.runtime_profile_id,
                    observed_control_version=control.control_version,
                    params=params,
                )
                runs[definition.key] = run
                session.add(run)
            await session.flush()
            for definition in definitions:
                for dependency in definition.depends_on:
                    session.add(
                        StageDependency(
                            stage_run_id=runs[definition.key].id,
                            depends_on_stage_run_id=runs[dependency].id,
                        )
                    )

            project.status = ProjectStatus.ANALYZING
            project.state_version += 1
            session.add(
                OutboxEvent(
                    workspace_id=workspace_id,
                    aggregate_type="job",
                    aggregate_id=job.id,
                    event_type="analysis.requested",
                    payload={
                        "job_id": str(job.id),
                        "project_id": str(project_id),
                        "episode_ids": [str(episode.id) for episode in episodes],
                    },
                )
            )
            await session.flush()
            return _job_read(job)

    async def get_job(self, workspace_id: UUID, job_id: UUID) -> JobRead:
        async with self._sessions() as session:
            job = await session.scalar(
                select(Job)
                .join(Project, Project.id == Job.project_id)
                .where(Job.id == job_id, Project.workspace_id == workspace_id)
            )
            if job is None:
                raise ProjectNotFoundError(job_id)
            return _job_read(job)

    async def create_artifact_release(
        self, workspace_id: UUID, project_id: UUID, payload: ArtifactReleaseCreate
    ) -> ArtifactReleaseRead:
        async with self._sessions.begin() as session:
            project = await session.scalar(
                select(Project).where(
                    Project.id == project_id, Project.workspace_id == workspace_id
                ).with_for_update()
            )
            if project is None:
                raise ProjectNotFoundError(project_id)
            asset = await session.scalar(
                select(MediaAsset.id).where(
                    MediaAsset.id == payload.content_asset_id,
                    MediaAsset.project_id == project_id,
                    MediaAsset.workspace_id == workspace_id,
                )
            )
            if asset is None:
                raise ProjectNotFoundError(payload.content_asset_id)
            dependency_ids = set(payload.dependency_release_ids)
            if payload.supersedes_release_id:
                dependency_ids.discard(payload.supersedes_release_id)
            if dependency_ids:
                found = set(
                    await session.scalars(
                        select(ArtifactRelease.id).where(
                            ArtifactRelease.project_id == project_id,
                            ArtifactRelease.id.in_(dependency_ids),
                        )
                    )
                )
                if found != dependency_ids:
                    raise ProjectNotFoundError("artifact dependency")
            if payload.supersedes_release_id:
                superseded = await session.scalar(
                    select(ArtifactRelease.id).where(
                        ArtifactRelease.id == payload.supersedes_release_id,
                        ArtifactRelease.project_id == project_id,
                        ArtifactRelease.artifact_type == payload.artifact_type,
                    )
                )
                if superseded is None:
                    raise ArtifactConflictError(
                        "superseded release must have the same artifact type"
                    )
            version = int(
                await session.scalar(
                    select(func.coalesce(func.max(ArtifactRelease.version), 0) + 1).where(
                        ArtifactRelease.project_id == project_id,
                        ArtifactRelease.artifact_type == payload.artifact_type,
                    )
                )
            )
            release = ArtifactRelease(
                id=self._id_factory(),
                project_id=project_id,
                artifact_type=payload.artifact_type,
                version=version,
                content_asset_id=payload.content_asset_id,
                supersedes_release_id=payload.supersedes_release_id,
            )
            session.add(release)
            await session.flush()
            session.add_all(
                ArtifactReleaseDependency(
                    upstream_release_id=dependency_id,
                    downstream_release_id=release.id,
                )
                for dependency_id in dependency_ids
            )
            stale_ids: list[UUID] = []
            if payload.supersedes_release_id:
                stale = await _invalidate_release_graph(
                    session, payload.supersedes_release_id, project_id, datetime.now(UTC)
                )
                stale_ids = [item.id for item in stale]
                if stale:
                    _add_release_event(
                        session,
                        workspace_id,
                        stale[0],
                        "artifact_release.invalidated",
                        {"stale_release_ids": [str(item) for item in stale_ids]},
                    )
            session.add(
                OutboxEvent(
                    workspace_id=workspace_id,
                    aggregate_type="artifact_release",
                    aggregate_id=release.id,
                    event_type="artifact_release.created",
                    payload={
                        "release_id": str(release.id),
                        "project_id": str(project_id),
                        "stale_release_ids": [str(item) for item in stale_ids],
                    },
                )
            )
            await session.flush()
            return await _artifact_read(session, release)

    async def list_artifact_releases(
        self, workspace_id: UUID, project_id: UUID
    ) -> list[ArtifactReleaseRead]:
        async with self._sessions() as session:
            exists = await session.scalar(
                select(Project.id).where(
                    Project.id == project_id, Project.workspace_id == workspace_id
                )
            )
            if exists is None:
                raise ProjectNotFoundError(project_id)
            releases = list(
                await session.scalars(
                    select(ArtifactRelease)
                    .where(ArtifactRelease.project_id == project_id)
                    .order_by(ArtifactRelease.artifact_type, ArtifactRelease.version.desc())
                )
            )
            return [await _artifact_read(session, release) for release in releases]

    async def confirm_artifact_release(
        self, workspace_id: UUID, release_id: UUID, actor_id: UUID, expected_state_version: int
    ) -> ArtifactReleaseRead:
        async with self._sessions.begin() as session:
            release = await _locked_release(session, workspace_id, release_id)
            try:
                changed = confirm_release(
                    _artifact_state(release),
                    actor_id=actor_id,
                    expected_state_version=expected_state_version,
                )
            except InvalidArtifactTransitionError as exc:
                raise ArtifactConflictError(str(exc)) from exc
            _apply_artifact_state(release, changed)
            _add_release_event(session, workspace_id, release, "artifact_release.confirmed")
            await session.flush()
            return await _artifact_read(session, release)

    async def publish_artifact_release(
        self, workspace_id: UUID, release_id: UUID, expected_state_version: int
    ) -> ArtifactReleaseRead:
        async with self._sessions.begin() as session:
            release = await _locked_release(session, workspace_id, release_id)
            dependencies = list(
                await session.scalars(
                    select(ArtifactRelease)
                    .join(
                        ArtifactReleaseDependency,
                        ArtifactReleaseDependency.upstream_release_id == ArtifactRelease.id,
                    )
                    .where(ArtifactReleaseDependency.downstream_release_id == release.id)
                    .with_for_update()
                )
            )
            try:
                changed = publish_release(
                    _artifact_state(release),
                    dependencies=tuple(_artifact_state(item) for item in dependencies),
                    expected_state_version=expected_state_version,
                )
            except InvalidArtifactTransitionError as exc:
                raise ArtifactConflictError(str(exc)) from exc
            _apply_artifact_state(release, changed)
            _add_release_event(session, workspace_id, release, "artifact_release.released")
            await session.flush()
            return await _artifact_read(session, release)

    async def invalidate_artifact_release(
        self, workspace_id: UUID, release_id: UUID, expected_state_version: int
    ) -> list[ArtifactReleaseRead]:
        async with self._sessions.begin() as session:
            root = await _locked_release(session, workspace_id, release_id)
            if root.state_version != expected_state_version:
                raise ArtifactConflictError("artifact state version mismatch")
            changed = await _invalidate_release_graph(
                session, root.id, root.project_id, datetime.now(UTC)
            )
            _add_release_event(
                session,
                workspace_id,
                root,
                "artifact_release.invalidated",
                {"stale_release_ids": [str(item.id) for item in changed]},
            )
            await session.flush()
            return [await _artifact_read(session, item) for item in changed]

    async def create_upload_session(
        self,
        workspace_id: UUID,
        upload_id: UUID,
        payload: MultipartInit,
        object_key: str,
        provider_upload_id: str,
    ) -> UploadRead:
        async with self._sessions.begin() as session:
            project_exists = await session.scalar(
                select(Project.id).where(
                    Project.id == payload.project_id,
                    Project.workspace_id == workspace_id,
                )
            )
            if project_exists is None:
                raise ProjectNotFoundError(payload.project_id)
            upload = UploadSession(
                id=upload_id,
                workspace_id=workspace_id,
                project_id=payload.project_id,
                episode_no=payload.episode_no,
                filename=payload.filename,
                content_type=payload.content_type,
                size_bytes=payload.size_bytes,
                part_size_bytes=payload.part_size_bytes,
                declared_sha256=payload.sha256,
                object_key=object_key,
                provider_upload_id=provider_upload_id,
                status="UPLOADING",
                completed_parts=[],
            )
            session.add(upload)
            await session.flush()
            return _upload_read(upload)

    async def get_upload(self, workspace_id: UUID, upload_id: UUID) -> UploadRecord:
        async with self._sessions() as session:
            upload = await session.scalar(
                select(UploadSession).where(
                    UploadSession.id == upload_id,
                    UploadSession.workspace_id == workspace_id,
                )
            )
            if upload is None:
                raise ProjectNotFoundError(upload_id)
            return _upload_record(upload)

    async def find_active_upload(
        self,
        workspace_id: UUID,
        project_id: UUID,
        sha256: str,
    ) -> UploadRecord | None:
        async with self._sessions() as session:
            upload = await session.scalar(
                select(UploadSession)
                .where(
                    UploadSession.workspace_id == workspace_id,
                    UploadSession.project_id == project_id,
                    UploadSession.declared_sha256 == sha256,
                    UploadSession.status == "UPLOADING",
                )
                .order_by(UploadSession.created_at.desc())
                .limit(1)
            )
            return _upload_record(upload) if upload else None

    async def record_upload_part(
        self,
        workspace_id: UUID,
        upload_id: UUID,
        part: UploadPart,
    ) -> UploadRead:
        async with self._sessions.begin() as session:
            upload = await session.scalar(
                select(UploadSession)
                .where(
                    UploadSession.id == upload_id,
                    UploadSession.workspace_id == workspace_id,
                )
                .with_for_update()
            )
            if upload is None:
                raise ProjectNotFoundError(upload_id)
            if upload.status != "UPLOADING":
                raise UploadConflictError(f"upload is already {upload.status}")
            if part.size_bytes > upload.part_size_bytes:
                raise UploadConflictError("part exceeds declared part size")
            completed = {
                item["part_number"]: item for item in upload.completed_parts
            }
            completed[part.part_number] = part.model_dump(mode="json")
            upload.completed_parts = [completed[number] for number in sorted(completed)]
            await session.flush()
            return _upload_read(upload)

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
        async with self._sessions.begin() as session:
            upload = await session.scalar(
                select(UploadSession)
                .where(
                    UploadSession.id == upload_id,
                    UploadSession.workspace_id == workspace_id,
                )
                .with_for_update()
            )
            if upload is None:
                raise ProjectNotFoundError(upload_id)
            if upload.status != "UPLOADING":
                raise UploadConflictError(f"upload is already {upload.status}")
            if upload.declared_sha256 != object_checksum_sha256:
                raise UploadConflictError("object SHA-256 does not match upload declaration")
            if upload.size_bytes != size_bytes:
                raise UploadConflictError("stored object size does not match upload declaration")

            episode_no = upload.episode_no
            if episode_no is None:
                episode_no = (
                    await session.scalar(
                        select(func.coalesce(func.max(Episode.episode_no), 0) + 1).where(
                            Episode.project_id == upload.project_id
                        )
                    )
                )
            episode = Episode(
                id=self._id_factory(),
                project_id=upload.project_id,
                episode_no=episode_no,
                title=upload.filename,
            )
            asset = MediaAsset(
                id=self._id_factory(),
                workspace_id=workspace_id,
                project_id=upload.project_id,
                object_uri=object_uri,
                sha256=object_checksum_sha256,
                size_bytes=size_bytes,
                content_type=content_type,
                metadata_json={"upload_id": str(upload.id), "filename": upload.filename},
            )
            job = Job(
                id=self._id_factory(),
                project_id=upload.project_id,
                kind="EPISODE_INGEST",
                status=JobStatus.QUEUED,
                idempotency_key=f"episode-ingest:{upload.id}",
                total_stages=len(EPISODE_BASELINE_DAG),
            )
            session.add_all([episode, asset, job])
            await session.flush()
            episode.source_asset_id = asset.id
            runs: dict[str, StageRun] = {}
            for definition in EPISODE_BASELINE_DAG:
                run = StageRun(
                    id=self._id_factory(),
                    job_id=job.id,
                    project_id=upload.project_id,
                    episode_id=episode.id,
                    stage_type=definition.stage_type,
                    status="READY" if not definition.depends_on else "PENDING",
                    idempotency_key=f"{job.id}:{definition.key}",
                    runtime_profile_id=definition.runtime_profile_id,
                    observed_control_version=1,
                    params={
                        "source_asset_id": str(asset.id),
                        "episode_id": str(episode.id),
                        "mock_baseline": True,
                    },
                )
                runs[definition.key] = run
                session.add(run)
            await session.flush()
            for definition in EPISODE_BASELINE_DAG:
                for dependency in definition.depends_on:
                    session.add(
                        StageDependency(
                            stage_run_id=runs[definition.key].id,
                            depends_on_stage_run_id=runs[dependency].id,
                        )
                    )
            upload.status = "COMPLETED"
            upload.completed_parts = [part.model_dump(mode="json") for part in parts]
            upload.object_checksum_sha256 = object_checksum_sha256
            upload.episode_id = episode.id
            upload.media_asset_id = asset.id
            upload.ingest_job_id = job.id
            session.add(
                OutboxEvent(
                    workspace_id=workspace_id,
                    aggregate_type="upload",
                    aggregate_id=upload.id,
                    event_type="upload.completed",
                    payload={
                        "upload_id": str(upload.id),
                        "episode_id": str(episode.id),
                        "media_asset_id": str(asset.id),
                        "ingest_job_id": str(job.id),
                    },
                )
            )
            await session.flush()
            return _upload_read(upload)

    async def register_orphan_asset(
        self,
        workspace_id: UUID,
        project_id: UUID,
        object_uri: str,
        reason: str,
    ) -> None:
        async with self._sessions.begin() as session:
            exists = await session.scalar(
                select(Project.id).where(
                    Project.id == project_id,
                    Project.workspace_id == workspace_id,
                )
            )
            if exists is None:
                raise ProjectNotFoundError(project_id)
            session.add(
                OrphanAsset(
                    id=self._id_factory(),
                    project_id=project_id,
                    object_uri=object_uri,
                    reason=reason,
                    delete_after=datetime.now(UTC) + timedelta(days=1),
                )
            )


def _project_read(project: Project) -> ProjectRead:
    return ProjectRead(
        id=project.id,
        workspace_id=project.workspace_id,
        name=project.name,
        target_market=project.target_market,
        locale=project.locale,
        timezone=project.timezone,
        quality_profile=project.quality_profile,
        output=project.output_spec,
        budget={
            "currency": project.budget_currency,
            "warning_at": Decimal(project.budget_warning_at),
            "hard_limit": Decimal(project.budget_hard_limit),
        },
        status=project.status,
        state_version=project.state_version,
        created_at=project.created_at or datetime.now(UTC),
        updated_at=project.updated_at or datetime.now(UTC),
    )


async def _locked_release(
    session: AsyncSession, workspace_id: UUID, release_id: UUID
) -> ArtifactRelease:
    release = await session.scalar(
        select(ArtifactRelease)
        .join(Project, Project.id == ArtifactRelease.project_id)
        .where(ArtifactRelease.id == release_id, Project.workspace_id == workspace_id)
        .with_for_update()
    )
    if release is None:
        raise ProjectNotFoundError(release_id)
    return release


def _artifact_state(release: ArtifactRelease) -> ArtifactReleaseState:
    return ArtifactReleaseState(
        release_id=release.id,
        status=ArtifactReleaseStatus(release.status),
        state_version=release.state_version,
        confirmed_by=release.confirmed_by,
        confirmed_at=release.confirmed_at,
        released_at=release.released_at,
        stale_at=release.stale_at,
    )


def _apply_artifact_state(release: ArtifactRelease, state: ArtifactReleaseState) -> None:
    release.status = state.status
    release.state_version = state.state_version
    release.confirmed_by = state.confirmed_by
    release.confirmed_at = state.confirmed_at
    release.released_at = state.released_at
    release.stale_at = state.stale_at


async def _artifact_read(
    session: AsyncSession, release: ArtifactRelease
) -> ArtifactReleaseRead:
    dependency_ids = tuple(
        await session.scalars(
            select(ArtifactReleaseDependency.upstream_release_id)
            .where(ArtifactReleaseDependency.downstream_release_id == release.id)
            .order_by(ArtifactReleaseDependency.upstream_release_id)
        )
    )
    return ArtifactReleaseRead(
        id=release.id,
        project_id=release.project_id,
        artifact_type=release.artifact_type,
        version=release.version,
        status=release.status,
        state_version=release.state_version,
        content_asset_id=release.content_asset_id,
        supersedes_release_id=release.supersedes_release_id,
        dependency_release_ids=dependency_ids,
        confirmed_by=release.confirmed_by,
        confirmed_at=release.confirmed_at,
        released_at=release.released_at,
        stale_at=release.stale_at,
        created_at=release.created_at,
        updated_at=release.updated_at,
    )


def _add_release_event(
    session: AsyncSession,
    workspace_id: UUID,
    release: ArtifactRelease,
    event_type: str,
    extra: dict | None = None,
) -> None:
    session.add(
        OutboxEvent(
            workspace_id=workspace_id,
            aggregate_type="artifact_release",
            aggregate_id=release.id,
            event_type=event_type,
            payload={"release_id": str(release.id), **(extra or {})},
        )
    )


async def _invalidate_release_graph(
    session: AsyncSession,
    root_release_id: UUID,
    project_id: UUID,
    now: datetime,
) -> list[ArtifactRelease]:
    changed: list[ArtifactRelease] = []
    pending = [root_release_id]
    visited: set[UUID] = set()
    while pending:
        current_id = pending.pop()
        if current_id in visited:
            continue
        visited.add(current_id)
        current = await session.get(ArtifactRelease, current_id, with_for_update=True)
        if current is None or current.project_id != project_id:
            raise ArtifactConflictError("artifact dependency crosses project boundary")
        if current.status != "STALE":
            current.status = "STALE"
            current.state_version += 1
            current.stale_at = now
            changed.append(current)
        downstream = await session.scalars(
            select(ArtifactReleaseDependency.downstream_release_id).where(
                ArtifactReleaseDependency.upstream_release_id == current_id
            )
        )
        pending.extend(downstream)
    return changed


def _job_read(job: Job) -> JobRead:
    progress = job.completed_stages / job.total_stages if job.total_stages else 0
    return JobRead(
        id=job.id,
        project_id=job.project_id,
        kind=job.kind,
        status=job.status,
        progress=progress,
        total_stages=job.total_stages,
        completed_stages=job.completed_stages,
    )


def _upload_read(upload: UploadSession) -> UploadRead:
    return UploadRead(
        upload_id=upload.id,
        project_id=upload.project_id,
        object_key=upload.object_key,
        size_bytes=upload.size_bytes,
        status=upload.status,
        completed_parts=[UploadPart.model_validate(part) for part in upload.completed_parts],
        episode_id=upload.episode_id,
        media_asset_id=upload.media_asset_id,
        ingest_job_id=upload.ingest_job_id,
    )


def _upload_record(upload: UploadSession) -> UploadRecord:
    return UploadRecord(
        upload=_upload_read(upload),
        provider_upload_id=upload.provider_upload_id,
        declared_sha256=upload.declared_sha256,
        content_type=upload.content_type,
        part_size_bytes=upload.part_size_bytes,
        filename=upload.filename,
        episode_no=upload.episode_no,
    )
