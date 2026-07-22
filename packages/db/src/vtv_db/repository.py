from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Protocol
from uuid import UUID, uuid4

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from vtv_evaluation import evaluate_release
from vtv_production import (
    LipSyncRequest,
    LocalizedUtterance,
    ReviewState,
    ShotDialogueFeatures,
    TieredLipSyncRouter,
    TtsRequest,
    Utterance,
    VoiceRelease,
    VoiceRightsSnapshot,
)
from vtv_schemas.analysis import AnalysisDocumentRead
from vtv_schemas.benchmarks import BenchmarkReleaseCreate, BenchmarkReleaseRead
from vtv_schemas.candidates import (
    CandidateAdopt,
    CandidateGroupRead,
    CandidateQcCreate,
    CandidateVariantRead,
    QcMetricRead,
)
from vtv_schemas.enums import JobStatus, ProjectStatus
from vtv_schemas.episodes import EpisodeRead
from vtv_schemas.jobs import JobRead
from vtv_schemas.model_releases import ModelReleaseCreate, ModelReleaseRead
from vtv_schemas.production import (
    DubbingJobCreate,
    DubbingUtteranceCreate,
    LipSyncJobCreate,
)
from vtv_schemas.projects import ProjectCreate, ProjectRead
from vtv_schemas.releases import ArtifactReleaseCreate, ArtifactReleaseRead
from vtv_schemas.rights import (
    RightsExecutionCheck,
    RightsExecutionDecision,
    RightsReleaseCreate,
    RightsReleaseRead,
)
from vtv_schemas.uploads import MultipartInit, UploadPart, UploadRead

from .dag import EPISODE_BASELINE_DAG, build_project_analysis_dag
from .model_registry import (
    AutomationStatus,
    InvalidModelReleaseTransitionError,
    LicenseStatus,
    ModelReleaseState,
    canary_receives_job,
    review_license,
    set_automation_status,
)
from .models import (
    AnalysisDocument,
    ArtifactRelease,
    ArtifactReleaseDependency,
    BenchmarkRelease,
    BenchmarkSampleResult,
    CandidateGroup,
    Episode,
    ExecutionControl,
    Job,
    MediaAsset,
    ModelRelease,
    OrphanAsset,
    OutboxEvent,
    Project,
    QcResult,
    RenderVariant,
    RightsRelease,
    Shot,
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
from .rights import evaluate_rights_release


class ProjectNotFoundError(KeyError):
    pass


class UploadConflictError(ValueError):
    pass


class AnalysisNotReadyError(ValueError):
    pass


class ArtifactConflictError(ValueError):
    pass


class ModelReleaseConflictError(ValueError):
    pass


class RightsReleaseConflictError(ValueError):
    pass


class ProductionNotReadyError(ValueError):
    pass


class CandidateConflictError(ValueError):
    pass


TTS_REQUIRED_QC_METRICS = frozenset(
    {
        "tts_intelligibility",
        "speaker_similarity",
        "emotion_fidelity",
        "duration_fit",
        "audio_artifact_control",
    }
)
LIPSYNC_REQUIRED_QC_METRICS = frozenset(
    {
        "technical_integrity",
        "identity_consistency",
        "temporal_stability",
        "structure_integrity",
        "lipsync_alignment",
        "continuity",
    }
)
REQUIRED_QC_METRICS_BY_PURPOSE = {
    "TTS": TTS_REQUIRED_QC_METRICS,
    "LIPSYNC": LIPSYNC_REQUIRED_QC_METRICS,
}

LIPSYNC_MODEL_KEYS = {
    "L1_FAST": "LIPSYNC_L1",
    "L2_PRESERVE_SOURCE": "LIPSYNC_L2",
    "L3_GENERATIVE_FACE": "LIPSYNC_L3",
    "L4_FULL_BODY": "LIPSYNC_L4",
    "L5_FULL_REGEN": "LIPSYNC_L5",
}


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
    async def list_candidate_groups(
        self, workspace_id: UUID, project_id: UUID, job_id: UUID | None = None
    ) -> list[CandidateGroupRead]: ...

    async def submit_candidate_qc(
        self, workspace_id: UUID, variant_id: UUID, payload: CandidateQcCreate
    ) -> CandidateVariantRead: ...

    async def adopt_candidate(
        self, workspace_id: UUID, group_id: UUID, payload: CandidateAdopt
    ) -> CandidateGroupRead: ...

    async def create_dubbing_job(
        self, workspace_id: UUID, project_id: UUID, payload: DubbingJobCreate
    ) -> JobRead: ...

    async def create_lipsync_job(
        self, workspace_id: UUID, project_id: UUID, payload: LipSyncJobCreate
    ) -> JobRead: ...

    async def create_rights_release(
        self, workspace_id: UUID, project_id: UUID, payload: RightsReleaseCreate
    ) -> RightsReleaseRead: ...

    async def list_rights_releases(
        self, workspace_id: UUID, project_id: UUID
    ) -> list[RightsReleaseRead]: ...

    async def revoke_rights_release(
        self,
        workspace_id: UUID,
        release_id: UUID,
        actor_id: UUID,
        reason: str,
        expected_state_version: int,
    ) -> RightsReleaseRead: ...

    async def check_rights_release(
        self, workspace_id: UUID, release_id: UUID, request: RightsExecutionCheck
    ) -> RightsExecutionDecision: ...

    async def create_benchmark_release(
        self, workspace_id: UUID, model_release_id: UUID, payload: BenchmarkReleaseCreate
    ) -> BenchmarkReleaseRead: ...

    async def list_benchmark_releases(
        self, workspace_id: UUID, model_release_id: UUID
    ) -> list[BenchmarkReleaseRead]: ...

    async def create_model_release(
        self, workspace_id: UUID, payload: ModelReleaseCreate
    ) -> ModelReleaseRead: ...

    async def list_model_releases(
        self, workspace_id: UUID, model_key: str | None = None
    ) -> list[ModelReleaseRead]: ...

    async def review_model_license(
        self,
        workspace_id: UUID,
        release_id: UUID,
        decision: str,
        actor_id: UUID,
        expected_state_version: int,
    ) -> ModelReleaseRead: ...

    async def update_model_automation(
        self,
        workspace_id: UUID,
        release_id: UUID,
        target: str,
        traffic_percent: int,
        expected_state_version: int,
    ) -> ModelReleaseRead: ...

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

    async def list_analysis_documents(
        self,
        workspace_id: UUID,
        project_id: UUID,
        episode_id: UUID | None = None,
        document_type: str | None = None,
    ) -> list[AnalysisDocumentRead]: ...

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

    async def create_benchmark_release(
        self, workspace_id: UUID, model_release_id: UUID, payload: BenchmarkReleaseCreate
    ) -> BenchmarkReleaseRead:
        async with self._sessions.begin() as session:
            release = await _locked_model_release(session, workspace_id, model_release_id)
            if release.state_version != payload.expected_model_state_version:
                raise ModelReleaseConflictError(
                    "model release state version mismatch: "
                    f"expected {payload.expected_model_state_version}, "
                    f"actual {release.state_version}"
                )
            report = evaluate_release(
                model_key=release.model_key,
                model_release=release.release_name,
                dataset=payload.dataset,
                policy=payload.policy,
                evidence=payload.evidence,
                results=payload.results,
            )
            benchmark = BenchmarkRelease(
                id=self._id_factory(),
                workspace_id=workspace_id,
                model_release_id=release.id,
                dataset_key=payload.dataset.dataset_key,
                dataset_release=payload.dataset.release,
                dataset_fingerprint=payload.dataset.fingerprint,
                annotation_release=payload.dataset.annotation_release,
                policy_key=payload.policy.policy_key,
                policy_release=payload.policy.release,
                policy_fingerprint=payload.policy.fingerprint,
                weights_sha256=payload.evidence.weights_sha256,
                runtime_fingerprint=payload.evidence.runtime_fingerprint,
                evidence=payload.evidence.model_dump(mode="json"),
                report=report.model_dump(mode="json"),
                approved=report.approved,
                failed_gates=list(report.failed_gates),
            )
            session.add(benchmark)
            sample_by_id = {sample.sample_id: sample for sample in payload.dataset.samples}
            for result in payload.results:
                sample = sample_by_id[result.sample_id]
                session.add(
                    BenchmarkSampleResult(
                        id=self._id_factory(),
                        benchmark_release_id=benchmark.id,
                        sample_id=result.sample_id,
                        source_sha256=sample.source_sha256,
                        critical=sample.critical,
                        result=result.model_dump(mode="json"),
                    )
                )
            if report.approved:
                release.approved_benchmark_release_id = benchmark.id
                release.state_version += 1
            session.add(
                OutboxEvent(
                    workspace_id=workspace_id,
                    aggregate_type="benchmark_release",
                    aggregate_id=benchmark.id,
                    event_type="benchmark_release.created",
                    payload={
                        "benchmark_release_id": str(benchmark.id),
                        "model_release_id": str(release.id),
                        "approved": report.approved,
                        "failed_gates": list(report.failed_gates),
                    },
                )
            )
            try:
                await session.flush()
            except IntegrityError as exc:
                raise ModelReleaseConflictError("benchmark release already exists") from exc
            return _benchmark_release_read(benchmark)

    async def list_benchmark_releases(
        self, workspace_id: UUID, model_release_id: UUID
    ) -> list[BenchmarkReleaseRead]:
        async with self._sessions() as session:
            release = await session.scalar(
                select(ModelRelease.id).where(
                    ModelRelease.id == model_release_id,
                    ModelRelease.workspace_id == workspace_id,
                )
            )
            if release is None:
                raise ProjectNotFoundError(model_release_id)
            rows = list(
                await session.scalars(
                    select(BenchmarkRelease)
                    .where(
                        BenchmarkRelease.workspace_id == workspace_id,
                        BenchmarkRelease.model_release_id == model_release_id,
                    )
                    .order_by(BenchmarkRelease.created_at.desc())
                )
            )
            return [_benchmark_release_read(row) for row in rows]

    async def create_model_release(
        self, workspace_id: UUID, payload: ModelReleaseCreate
    ) -> ModelReleaseRead:
        async with self._sessions.begin() as session:
            await session.execute(
                insert(Workspace)
                .values(id=workspace_id, name=f"Workspace {workspace_id}")
                .on_conflict_do_nothing(index_elements=[Workspace.id])
            )
            if payload.fallback_release_id:
                fallback = await session.scalar(
                    select(ModelRelease).where(
                        ModelRelease.id == payload.fallback_release_id,
                        ModelRelease.workspace_id == workspace_id,
                        ModelRelease.model_key == payload.model_key,
                    )
                )
                if fallback is None:
                    raise ProjectNotFoundError(payload.fallback_release_id)
            release = ModelRelease(
                id=self._id_factory(),
                workspace_id=workspace_id,
                model_key=payload.model_key,
                release_name=payload.release_name,
                provider=payload.provider,
                endpoint=payload.endpoint,
                license_id=payload.license_id,
                model_card_uri=payload.model_card_uri,
                config_json=payload.config,
                fallback_release_id=payload.fallback_release_id,
            )
            session.add(release)
            session.add(
                OutboxEvent(
                    workspace_id=workspace_id,
                    aggregate_type="model_release",
                    aggregate_id=release.id,
                    event_type="model_release.created",
                    payload={"release_id": str(release.id), "model_key": release.model_key},
                )
            )
            try:
                await session.flush()
            except IntegrityError as exc:
                raise ModelReleaseConflictError("model release already exists") from exc
            return _model_release_read(release)

    async def list_model_releases(
        self, workspace_id: UUID, model_key: str | None = None
    ) -> list[ModelReleaseRead]:
        async with self._sessions() as session:
            query = select(ModelRelease).where(ModelRelease.workspace_id == workspace_id)
            if model_key:
                query = query.where(ModelRelease.model_key == model_key)
            releases = list(
                await session.scalars(query.order_by(ModelRelease.created_at.desc()))
            )
            return [_model_release_read(release) for release in releases]

    async def review_model_license(
        self,
        workspace_id: UUID,
        release_id: UUID,
        decision: str,
        actor_id: UUID,
        expected_state_version: int,
    ) -> ModelReleaseRead:
        async with self._sessions.begin() as session:
            release = await _locked_model_release(session, workspace_id, release_id)
            try:
                changed = review_license(
                    _model_release_state(release),
                    decision=LicenseStatus(decision),
                    actor_id=actor_id,
                    expected_state_version=expected_state_version,
                )
            except InvalidModelReleaseTransitionError as exc:
                raise ModelReleaseConflictError(str(exc)) from exc
            _apply_model_release_state(release, changed)
            _add_model_release_event(session, workspace_id, release, "model_release.reviewed")
            await session.flush()
            return _model_release_read(release)

    async def update_model_automation(
        self,
        workspace_id: UUID,
        release_id: UUID,
        target: str,
        traffic_percent: int,
        expected_state_version: int,
    ) -> ModelReleaseRead:
        async with self._sessions.begin() as session:
            release = await _locked_model_release(session, workspace_id, release_id)
            target_status = AutomationStatus(target)
            if target_status in {AutomationStatus.CANARY, AutomationStatus.ACTIVE}:
                approved_benchmark = await session.scalar(
                    select(BenchmarkRelease.id).where(
                        BenchmarkRelease.id == release.approved_benchmark_release_id,
                        BenchmarkRelease.workspace_id == workspace_id,
                        BenchmarkRelease.model_release_id == release.id,
                        BenchmarkRelease.approved.is_(True),
                    )
                )
                if approved_benchmark is None:
                    raise ModelReleaseConflictError(
                        "model release has no valid approved benchmark release"
                    )
            others = list(
                await session.scalars(
                    select(ModelRelease)
                    .where(
                        ModelRelease.workspace_id == workspace_id,
                        ModelRelease.model_key == release.model_key,
                        ModelRelease.id != release.id,
                        ModelRelease.automation_status.in_(("CANARY", "ACTIVE")),
                    )
                    .with_for_update()
                )
            )
            active = [item for item in others if item.automation_status == "ACTIVE"]
            canary = [item for item in others if item.automation_status == "CANARY"]
            if len(active) > 1 or len(canary) > 1:
                raise ModelReleaseConflictError("model registry has conflicting traffic state")
            if target_status is AutomationStatus.CANARY:
                if canary:
                    raise ModelReleaseConflictError("a canary release already exists")
                if not active:
                    raise ModelReleaseConflictError("canary requires an ACTIVE baseline release")
            if target_status is AutomationStatus.ACTIVE:
                if canary:
                    raise ModelReleaseConflictError(
                        "another canary release must be disabled before direct activation"
                    )
                if active and release.automation_status != "CANARY":
                    raise ModelReleaseConflictError(
                        "activate through canary or disable the current ACTIVE release first"
                    )
                if active:
                    previous = active[0]
                    disabled = set_automation_status(
                        _model_release_state(previous),
                        target=AutomationStatus.DISABLED,
                        traffic_percent=0,
                        expected_state_version=previous.state_version,
                    )
                    _apply_model_release_state(previous, disabled)
                    _add_model_release_event(
                        session,
                        workspace_id,
                        previous,
                        "model_release.automation_changed",
                    )
            try:
                changed = set_automation_status(
                    _model_release_state(release),
                    target=target_status,
                    traffic_percent=traffic_percent,
                    expected_state_version=expected_state_version,
                )
            except InvalidModelReleaseTransitionError as exc:
                raise ModelReleaseConflictError(str(exc)) from exc
            _apply_model_release_state(release, changed)
            _add_model_release_event(
                session, workspace_id, release, "model_release.automation_changed"
            )
            await session.flush()
            return _model_release_read(release)

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
            release_types = (
                "LOCALIZATION_BIBLE",
                "ANCHOR_PACK",
                "CONTINUITY_SNAPSHOT_SET",
            )
            next_release_versions = {
                artifact_type: int(
                    await session.scalar(
                        select(func.coalesce(func.max(ArtifactRelease.version), 0) + 1).where(
                            ArtifactRelease.project_id == project_id,
                            ArtifactRelease.artifact_type == artifact_type,
                        )
                    )
                )
                for artifact_type in release_types
            }
            job = Job(
                id=self._id_factory(),
                project_id=project_id,
                kind="PROJECT_ANALYSIS",
                status=JobStatus.QUEUED,
                idempotency_key=f"project-analysis:{project.state_version}",
                total_stages=len(definitions),
            )
            session.add(job)
            selected_releases = {
                model_key: await _select_model_release(
                    session, workspace_id, model_key, job.id
                )
                for model_key in (
                    "AUDIO_STEM_SEPARATION",
                    "AUDIO_ANALYSIS",
                    "VISION_ANALYSIS",
                )
            }
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
                if definition.stage_type == "PROJECT_SYNTHESIS":
                    params["release_versions"] = next_release_versions
                model_key = {
                    "AUDIO_STEM_SEPARATION": "AUDIO_STEM_SEPARATION",
                    "ASR_ALIGN": "AUDIO_ANALYSIS",
                    "VISION_ANALYSIS": "VISION_ANALYSIS",
                }.get(definition.stage_type)
                selected_release = selected_releases.get(model_key) if model_key else None
                if selected_release is not None:
                    params["model_runtime"] = {
                        "model_key": selected_release.model_key,
                        "endpoint": selected_release.endpoint,
                        "release": selected_release.release_name,
                        "license_id": selected_release.license_id,
                        "approved_for_automation": True,
                        "config": selected_release.config_json,
                    }
                run = StageRun(
                    id=self._id_factory(),
                    job_id=job.id,
                    project_id=project_id,
                    episode_id=definition.episode_id,
                    stage_type=definition.stage_type,
                    status="READY" if not definition.depends_on else "PENDING",
                    idempotency_key=f"{job.id}:{definition.key}",
                    runtime_profile_id=definition.runtime_profile_id,
                    model_release_id=selected_release.id if selected_release else None,
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

    async def list_candidate_groups(
        self, workspace_id: UUID, project_id: UUID, job_id: UUID | None = None
    ) -> list[CandidateGroupRead]:
        async with self._sessions() as session:
            exists = await session.scalar(
                select(Project.id).where(
                    Project.id == project_id, Project.workspace_id == workspace_id
                )
            )
            if exists is None:
                raise ProjectNotFoundError(project_id)
            query = select(CandidateGroup).where(CandidateGroup.project_id == project_id)
            if job_id is not None:
                job = await session.scalar(
                    select(Job.id).where(Job.id == job_id, Job.project_id == project_id)
                )
                if job is None:
                    raise ProjectNotFoundError(job_id)
                query = query.join(
                    StageRun, StageRun.candidate_group_id == CandidateGroup.id
                ).where(StageRun.job_id == job_id)
            groups = list(
                await session.scalars(query.distinct().order_by(CandidateGroup.created_at))
            )
            return [await _candidate_group_read(session, item) for item in groups]

    async def submit_candidate_qc(
        self, workspace_id: UUID, variant_id: UUID, payload: CandidateQcCreate
    ) -> CandidateVariantRead:
        async with self._sessions.begin() as session:
            variant = await session.scalar(
                select(RenderVariant)
                .join(
                    CandidateGroup,
                    CandidateGroup.id == RenderVariant.candidate_group_id,
                )
                .join(Project, Project.id == CandidateGroup.project_id)
                .where(
                    RenderVariant.id == variant_id,
                    Project.workspace_id == workspace_id,
                )
                .with_for_update()
            )
            if variant is None:
                raise ProjectNotFoundError(variant_id)
            if variant.status != "GENERATED":
                raise CandidateConflictError(
                    "QC can only be submitted once for a generated variant"
                )
            group = await session.get(
                CandidateGroup, variant.candidate_group_id, with_for_update=True
            )
            if group is None or group.status != "OPEN":
                raise CandidateConflictError("candidate group is no longer open")
            metric_names = {item.metric_name for item in payload.metrics}
            required_metrics = REQUIRED_QC_METRICS_BY_PURPOSE.get(group.purpose)
            if required_metrics and not required_metrics.issubset(metric_names):
                missing = sorted(required_metrics - metric_names)
                raise CandidateConflictError(
                    f"{group.purpose} QC evidence is incomplete: {missing}"
                )
            for metric in payload.metrics:
                session.add(
                    QcResult(
                        id=self._id_factory(),
                        render_variant_id=variant.id,
                        metric_name=metric.metric_name,
                        metric_version=metric.metric_version,
                        evaluator_release=metric.evaluator_release,
                        score=metric.score,
                        verdict=metric.verdict,
                        hard_failure=metric.hard_failure,
                        details=metric.details,
                    )
                )
            if any(item.hard_failure or item.verdict == "FAIL" for item in payload.metrics):
                variant.status = "QC_FAILED"
            elif any(item.verdict == "REVIEW" for item in payload.metrics):
                variant.status = "REVIEW"
            else:
                variant.status = "QC_PASSED"
            session.add(
                OutboxEvent(
                    workspace_id=workspace_id,
                    aggregate_type="render_variant",
                    aggregate_id=variant.id,
                    event_type="candidate.qc_recorded",
                    payload={
                        "variant_id": str(variant.id),
                        "candidate_group_id": str(group.id),
                        "status": variant.status,
                    },
                )
            )
            try:
                await session.flush()
            except IntegrityError as exc:
                raise CandidateConflictError("QC metric evidence already exists") from exc
            return await _candidate_variant_read(session, variant)

    async def adopt_candidate(
        self, workspace_id: UUID, group_id: UUID, payload: CandidateAdopt
    ) -> CandidateGroupRead:
        async with self._sessions.begin() as session:
            group = await session.scalar(
                select(CandidateGroup)
                .join(Project, Project.id == CandidateGroup.project_id)
                .where(
                    CandidateGroup.id == group_id,
                    Project.workspace_id == workspace_id,
                )
                .with_for_update()
            )
            if group is None:
                raise ProjectNotFoundError(group_id)
            if group.state_version != payload.expected_state_version:
                raise CandidateConflictError("candidate group state version mismatch")
            if group.status != "OPEN" or group.adopted_variant_id is not None:
                raise CandidateConflictError("candidate group already has an adopted variant")
            variant = await session.scalar(
                select(RenderVariant)
                .where(
                    RenderVariant.id == payload.variant_id,
                    RenderVariant.candidate_group_id == group.id,
                )
                .with_for_update()
            )
            if variant is None:
                raise ProjectNotFoundError(payload.variant_id)
            if variant.status != "QC_PASSED":
                raise CandidateConflictError("only a QC_PASSED variant can be adopted")
            run = await session.get(StageRun, variant.stage_run_id, with_for_update=True)
            if run is None:
                raise ProjectNotFoundError(variant.stage_run_id)
            rights_failure = await _stage_rights_failure(session, run)
            if rights_failure is not None:
                raise CandidateConflictError(f"RIGHTS_BLOCKED: {rights_failure}")
            group.status = "ADOPTED"
            group.state_version += 1
            group.adopted_variant_id = variant.id
            variant.status = "ADOPTED"
            run.status = "ADOPTED"
            await session.execute(
                update(RenderVariant)
                .where(
                    RenderVariant.candidate_group_id == group.id,
                    RenderVariant.id != variant.id,
                )
                .values(status="REJECTED")
            )
            session.add(
                OutboxEvent(
                    workspace_id=workspace_id,
                    aggregate_type="candidate_group",
                    aggregate_id=group.id,
                    event_type="candidate.adopted",
                    payload={
                        "candidate_group_id": str(group.id),
                        "variant_id": str(variant.id),
                        "actor_id": str(payload.actor_id),
                    },
                )
            )
            await session.flush()
            return await _candidate_group_read(session, group)

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

    async def create_dubbing_job(
        self, workspace_id: UUID, project_id: UUID, payload: DubbingJobCreate
    ) -> JobRead:
        async with self._sessions.begin() as session:
            project = await session.scalar(
                select(Project)
                .where(Project.id == project_id, Project.workspace_id == workspace_id)
                .with_for_update()
            )
            if project is None:
                raise ProjectNotFoundError(project_id)
            idempotency_key = f"episode-dubbing:{payload.fingerprint}"
            existing = await session.scalar(
                select(Job).where(
                    Job.project_id == project_id,
                    Job.idempotency_key == idempotency_key,
                )
            )
            if existing is not None:
                return _job_read(existing)
            control = await session.get(ExecutionControl, project_id, with_for_update=True)
            if control is None:
                raise RuntimeError("project execution control is missing")
            if control.cancel_requested or control.hard_budget_blocked:
                raise ProductionNotReadyError("project execution control blocks production")
            episode = await session.scalar(
                select(Episode).where(
                    Episode.id == payload.episode_id,
                    Episode.project_id == project_id,
                    Episode.source_asset_id.is_not(None),
                )
            )
            if episode is None:
                raise ProjectNotFoundError(payload.episode_id)
            localization = await session.scalar(
                select(ArtifactRelease).where(
                    ArtifactRelease.id == payload.localization_release_id,
                    ArtifactRelease.project_id == project_id,
                    ArtifactRelease.artifact_type.in_(
                        ("LOCALIZATION_BIBLE", "LOCALIZATION_UTTERANCES")
                    ),
                    ArtifactRelease.status == "RELEASED",
                )
            )
            if localization is None:
                raise ProductionNotReadyError(
                    "dubbing requires a released localization artifact"
                )
            job_id = self._id_factory()
            selected = await _select_model_release(session, workspace_id, "TTS", job_id)
            if selected is None:
                raise ProductionNotReadyError("no ACTIVE TTS model release is available")
            if selected.config_json.get("adapter_mode") != "remote_tts":
                raise ProductionNotReadyError("ACTIVE TTS release must select remote_tts")
            voice_ids = {item.voice_release_id for item in payload.utterances}
            voice_rows = list(
                await session.execute(
                    select(ArtifactRelease, MediaAsset)
                    .join(MediaAsset, MediaAsset.id == ArtifactRelease.content_asset_id)
                    .where(
                        ArtifactRelease.id.in_(voice_ids),
                        ArtifactRelease.project_id == project_id,
                        ArtifactRelease.artifact_type == "VOICE_RELEASE",
                        ArtifactRelease.status == "RELEASED",
                        MediaAsset.workspace_id == workspace_id,
                        MediaAsset.project_id == project_id,
                    )
                )
            )
            voices = {release.id: (release, asset) for release, asset in voice_rows}
            if set(voices) != voice_ids:
                raise ProductionNotReadyError(
                    "dubbing requires released voice artifacts with valid content assets"
                )
            rights_ids = {item.rights_release_id for item in payload.utterances}
            rights_rows = list(
                await session.scalars(
                    select(RightsRelease)
                    .where(
                        RightsRelease.id.in_(rights_ids),
                        RightsRelease.project_id == project_id,
                    )
                    .with_for_update()
                )
            )
            rights_by_id = {item.id: item for item in rights_rows}
            if set(rights_by_id) != rights_ids:
                raise ProjectNotFoundError("rights release")
            now = datetime.now(UTC)
            requests: list[tuple[DubbingUtteranceCreate, TtsRequest]] = []
            for item in payload.utterances:
                if item.target_language != project.locale:
                    raise ProductionNotReadyError(
                        "utterance target language must match project locale"
                    )
                rights = _rights_release_read(rights_by_id[item.rights_release_id])
                if rights.subject_type != "VOICE" or rights.subject_id != item.character_id:
                    raise ProductionNotReadyError(
                        "voice rights subject must match utterance character"
                    )
                check = RightsExecutionCheck(
                    operation="voice_clone",
                    market=project.target_market,
                    language=project.locale,
                    commercial_use=payload.commercial_use,
                    at=now,
                )
                decision = evaluate_rights_release(rights, check)
                if not decision.allowed:
                    raise ProductionNotReadyError(
                        f"RIGHTS_BLOCKED: {','.join(decision.reason_codes)}"
                    )
                _, voice_asset = voices[item.voice_release_id]
                requests.append(
                    (
                        item,
                        _build_tts_request(
                            item,
                            target_market=project.target_market,
                            localization_release_id=localization.id,
                            voice_release_id=item.voice_release_id,
                            voice_reference_sha256=voice_asset.sha256,
                            rights=rights,
                            selected_model_release=selected.release_name,
                            commercial_use=payload.commercial_use,
                        ),
                    )
                )
            job = Job(
                id=job_id,
                project_id=project_id,
                kind="EPISODE_DUBBING_CANDIDATES",
                status=JobStatus.QUEUED,
                idempotency_key=idempotency_key,
                total_stages=len(requests),
            )
            session.add(job)
            for item, request in requests:
                group = CandidateGroup(
                    id=self._id_factory(),
                    project_id=project_id,
                    purpose="TTS",
                )
                session.add(group)
                session.add(
                    StageRun(
                        id=self._id_factory(),
                        job_id=job.id,
                        project_id=project_id,
                        episode_id=episode.id,
                        candidate_group_id=group.id,
                        stage_type="TTS_GENERATE",
                        status="READY",
                        idempotency_key=f"{job.id}:tts:{item.utterance_id}",
                        model_release_id=selected.id,
                        runtime_profile_id="gpu-audio",
                        observed_control_version=control.control_version,
                        params={
                            "tts_request": request.model_dump(mode="json"),
                            "maximum_duration_deviation": item.maximum_duration_deviation,
                            "rights_state_version": request.voice_release.rights.state_version,
                            "model_runtime": {
                                "model_key": selected.model_key,
                                "endpoint": selected.endpoint,
                                "release": selected.release_name,
                                "license_id": selected.license_id,
                                "approved_for_automation": True,
                                "config": selected.config_json,
                            },
                        },
                    )
                )
            project.status = ProjectStatus.PRODUCING
            project.state_version += 1
            session.add(
                OutboxEvent(
                    workspace_id=workspace_id,
                    aggregate_type="job",
                    aggregate_id=job.id,
                    event_type="dubbing.requested",
                    payload={
                        "job_id": str(job.id),
                        "project_id": str(project_id),
                        "episode_id": str(episode.id),
                        "utterance_count": len(requests),
                        "localization_release_id": str(localization.id),
                    },
                )
            )
            await session.flush()
            return _job_read(job)

    async def create_lipsync_job(
        self, workspace_id: UUID, project_id: UUID, payload: LipSyncJobCreate
    ) -> JobRead:
        async with self._sessions.begin() as session:
            project = await session.scalar(
                select(Project)
                .where(Project.id == project_id, Project.workspace_id == workspace_id)
                .with_for_update()
            )
            if project is None:
                raise ProjectNotFoundError(project_id)
            idempotency_key = f"episode-lipsync:{payload.fingerprint}"
            existing = await session.scalar(
                select(Job).where(
                    Job.project_id == project_id,
                    Job.idempotency_key == idempotency_key,
                )
            )
            if existing is not None:
                return _job_read(existing)
            control = await session.get(ExecutionControl, project_id, with_for_update=True)
            if control is None:
                raise RuntimeError("project execution control is missing")
            if control.cancel_requested or control.hard_budget_blocked:
                raise ProductionNotReadyError("project execution control blocks production")
            episode = await session.scalar(
                select(Episode).where(
                    Episode.id == payload.episode_id,
                    Episode.project_id == project_id,
                )
            )
            if episode is None:
                raise ProjectNotFoundError(payload.episode_id)
            job_id = self._id_factory()
            router = TieredLipSyncRouter()
            selected_releases: dict[str, ModelRelease] = {}
            planned: list[tuple] = []
            for item in payload.shots:
                shot = await session.scalar(
                    select(Shot).where(
                        Shot.id == item.shot_id,
                        Shot.episode_id == episode.id,
                    )
                )
                if shot is None:
                    raise ProjectNotFoundError(item.shot_id)
                shot_duration = (shot.end_ms - shot.start_ms) / 1000
                if item.dialogue_duration_seconds > shot_duration + 0.05:
                    raise ProductionNotReadyError(
                        "dialogue duration cannot exceed authoritative shot duration"
                    )
                source_asset = await session.scalar(
                    select(MediaAsset).where(
                        MediaAsset.id == item.source_video_asset_id,
                        MediaAsset.workspace_id == workspace_id,
                        MediaAsset.project_id == project_id,
                    )
                )
                if source_asset is None or not source_asset.content_type.startswith("video/"):
                    raise ProductionNotReadyError("lipsync source must be a project video asset")
                source_duration = source_asset.metadata_json.get("duration_seconds")
                if source_asset.metadata_json.get("shot_id") != str(item.shot_id):
                    raise ProductionNotReadyError(
                        "lipsync source asset must be bound to the requested shot"
                    )
                if not isinstance(source_duration, (int, float)) or source_duration <= 0:
                    raise ProductionNotReadyError(
                        "lipsync source asset requires duration_seconds metadata"
                    )
                if abs(float(source_duration) - shot_duration) > max(0.05, shot_duration * 0.02):
                    raise ProductionNotReadyError(
                        "lipsync source asset duration must match authoritative shot"
                    )
                variant = await session.scalar(
                    select(RenderVariant)
                    .join(CandidateGroup, CandidateGroup.id == RenderVariant.candidate_group_id)
                    .where(
                        RenderVariant.id == item.adopted_tts_variant_id,
                        RenderVariant.status == "ADOPTED",
                        CandidateGroup.project_id == project_id,
                        CandidateGroup.purpose == "TTS",
                        CandidateGroup.adopted_variant_id == RenderVariant.id,
                    )
                )
                if variant is None:
                    raise ProductionNotReadyError(
                        "lipsync requires the uniquely adopted TTS variant"
                    )
                tts_run = await session.get(StageRun, variant.stage_run_id)
                audio_asset = await session.get(MediaAsset, variant.output_asset_id)
                if (
                    tts_run is None
                    or tts_run.episode_id != episode.id
                    or audio_asset is None
                    or not audio_asset.content_type.startswith("audio/")
                ):
                    raise ProductionNotReadyError(
                        "adopted TTS variant does not belong to the requested episode"
                    )
                try:
                    tts_request = tts_run.params["tts_request"]
                    localized = tts_request["localized"]
                    snapshot = tts_request["voice_release"]["rights"]
                    rights_id = UUID(snapshot["rights_release_id"])
                except (KeyError, TypeError, ValueError) as exc:
                    raise ProductionNotReadyError(
                        "adopted TTS variant has invalid rights provenance"
                    ) from exc
                rights_row = await session.scalar(
                    select(RightsRelease)
                    .where(
                        RightsRelease.id == rights_id,
                        RightsRelease.project_id == project_id,
                    )
                    .with_for_update()
                )
                if rights_row is None:
                    raise ProductionNotReadyError("RIGHTS_BLOCKED: RIGHTS_RELEASE_MISSING")
                rights = _rights_release_read(rights_row)
                decision = evaluate_rights_release(
                    rights,
                    RightsExecutionCheck(
                        operation="lipsync",
                        market=project.target_market,
                        language=project.locale,
                        commercial_use=payload.commercial_use,
                    ),
                )
                if not decision.allowed:
                    raise ProductionNotReadyError(
                        f"RIGHTS_BLOCKED: {','.join(decision.reason_codes)}"
                    )
                features = ShotDialogueFeatures(
                    shot_id=item.shot_id,
                    mouth_visible=item.mouth_visible,
                    face_scale=item.face_scale,
                    occlusion=item.occlusion,
                    body_visible=item.body_visible,
                    dialogue_duration_seconds=item.dialogue_duration_seconds,
                    original_performance_reusable=item.original_performance_reusable,
                    full_regeneration_required=item.full_regeneration_required,
                )
                route = router.route(features)
                candidate_count = 1 if route.level == "L0_NONE" else item.candidate_count
                model_release = None
                if route.level != "L0_NONE":
                    model_key = LIPSYNC_MODEL_KEYS[route.level]
                    model_release = selected_releases.get(model_key)
                    if model_release is None:
                        model_release = await _select_model_release(
                            session, workspace_id, model_key, job_id
                        )
                        if model_release is None:
                            raise ProductionNotReadyError(
                                f"no ACTIVE/CANARY model release is available for {model_key}"
                            )
                        if model_release.config_json.get("adapter_mode") != "remote_lipsync":
                            raise ProductionNotReadyError(
                                f"{model_key} release must use remote_lipsync runtime"
                            )
                        selected_releases[model_key] = model_release
                request = LipSyncRequest(
                    features=features,
                    decision=route,
                    source_video_sha256=source_asset.sha256,
                    source_video_duration_seconds=float(source_duration),
                    adopted_tts_variant_id=variant.id,
                    audio_sha256=audio_asset.sha256,
                    target_language=localized["target_language"],
                    target_market=localized["target_market"],
                    rights=VoiceRightsSnapshot(
                        rights_release_id=rights.id,
                        state_version=rights.state_version,
                        subject_id=rights.subject_id,
                        allowed_operations=frozenset(rights.allowed_operations),
                        allowed_languages=frozenset(rights.allowed_languages),
                        allowed_markets=frozenset(rights.allowed_markets),
                        commercial_allowed=rights.commercial_scope == "COMMERCIAL",
                        valid_at_execution=True,
                    ),
                    seed=item.seed,
                    candidate_count=candidate_count,
                    commercial_use=payload.commercial_use,
                )
                planned.append((item, request, source_asset, audio_asset, model_release))
            job = Job(
                id=job_id,
                project_id=project_id,
                kind="EPISODE_LIPSYNC_CANDIDATES",
                status=JobStatus.QUEUED,
                idempotency_key=idempotency_key,
                total_stages=len(planned),
            )
            session.add(job)
            for item, request, source_asset, audio_asset, model_release in planned:
                group = CandidateGroup(
                    id=self._id_factory(),
                    project_id=project_id,
                    shot_id=item.shot_id,
                    purpose="LIPSYNC",
                )
                params = {
                    "lipsync_request": request.model_dump(mode="json"),
                    "router_release": router.router_release,
                    "rights_state_version": request.rights.state_version,
                    "input_asset_ids": [str(source_asset.id), str(audio_asset.id)],
                }
                if model_release is not None:
                    params["model_runtime"] = {
                        "model_key": model_release.model_key,
                        "endpoint": model_release.endpoint,
                        "release": model_release.release_name,
                        "license_id": model_release.license_id,
                        "approved_for_automation": True,
                        "config": model_release.config_json,
                    }
                session.add(group)
                session.add(
                    StageRun(
                        id=self._id_factory(),
                        job_id=job.id,
                        project_id=project_id,
                        episode_id=episode.id,
                        shot_id=item.shot_id,
                        candidate_group_id=group.id,
                        stage_type="LIPSYNC_GENERATE",
                        status="READY",
                        idempotency_key=f"{job.id}:lipsync:{item.shot_id}",
                        model_release_id=(model_release.id if model_release else None),
                        runtime_profile_id=("cpu-media" if model_release is None else "gpu-render"),
                        observed_control_version=control.control_version,
                        params=params,
                    )
                )
            project.status = ProjectStatus.PRODUCING
            project.state_version += 1
            session.add(
                OutboxEvent(
                    workspace_id=workspace_id,
                    aggregate_type="job",
                    aggregate_id=job.id,
                    event_type="lipsync.requested",
                    payload={
                        "job_id": str(job.id),
                        "project_id": str(project_id),
                        "episode_id": str(episode.id),
                        "shot_count": len(planned),
                        "router_release": router.router_release,
                    },
                )
            )
            await session.flush()
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

    async def create_rights_release(
        self, workspace_id: UUID, project_id: UUID, payload: RightsReleaseCreate
    ) -> RightsReleaseRead:
        async with self._sessions.begin() as session:
            project = await session.scalar(
                select(Project).where(
                    Project.id == project_id, Project.workspace_id == workspace_id
                ).with_for_update()
            )
            if project is None:
                raise ProjectNotFoundError(project_id)
            current = await session.scalar(
                select(RightsRelease)
                .where(
                    RightsRelease.project_id == project_id,
                    RightsRelease.subject_type == payload.subject_type,
                    RightsRelease.subject_id == payload.subject_id,
                    RightsRelease.revoked_at.is_(None),
                )
                .with_for_update()
            )
            if current is not None and payload.supersedes_release_id != current.id:
                raise RightsReleaseConflictError(
                    "current rights release must be explicitly superseded"
                )
            if current is None and payload.supersedes_release_id is not None:
                raise RightsReleaseConflictError("superseded rights release is not current")
            source_ids = set(payload.source_asset_ids)
            if source_ids:
                found = set(
                    await session.scalars(
                        select(MediaAsset.id).where(
                            MediaAsset.id.in_(source_ids),
                            MediaAsset.workspace_id == workspace_id,
                            MediaAsset.project_id == project_id,
                        )
                    )
                )
                if found != source_ids:
                    raise ProjectNotFoundError("rights source asset")
            now = datetime.now(UTC)
            if current is not None:
                current.status = "REVOKED"
                current.state_version += 1
                current.revoked_at = now
                current.revoked_by = payload.created_by
                current.revocation_reason = "SUPERSEDED"
                await session.flush()
            version = int(
                await session.scalar(
                    select(func.coalesce(func.max(RightsRelease.version), 0) + 1).where(
                        RightsRelease.project_id == project_id,
                        RightsRelease.subject_type == payload.subject_type,
                        RightsRelease.subject_id == payload.subject_id,
                    )
                )
            )
            release = RightsRelease(
                id=self._id_factory(),
                project_id=project_id,
                subject_type=payload.subject_type,
                subject_id=payload.subject_id,
                version=version,
                allowed_operations=sorted(payload.allowed_operations),
                allowed_markets=sorted(payload.allowed_markets),
                allowed_languages=sorted(payload.allowed_languages),
                commercial_scope=payload.commercial_scope,
                valid_from=payload.valid_from,
                expires_at=payload.expires_at,
                minor_guardian_consent=payload.minor_guardian_consent,
                source_asset_ids=[str(value) for value in payload.source_asset_ids],
                evidence_uri=payload.evidence_uri,
                evidence_sha256=payload.evidence_sha256,
                supersedes_release_id=payload.supersedes_release_id,
                created_by=payload.created_by,
            )
            session.add(release)
            session.add(
                OutboxEvent(
                    workspace_id=workspace_id,
                    aggregate_type="rights_release",
                    aggregate_id=release.id,
                    event_type="rights_release.created",
                    payload={
                        "release_id": str(release.id),
                        "project_id": str(project_id),
                        "subject_type": release.subject_type,
                        "subject_id": release.subject_id,
                    },
                )
            )
            await session.flush()
            return _rights_release_read(release)

    async def list_rights_releases(
        self, workspace_id: UUID, project_id: UUID
    ) -> list[RightsReleaseRead]:
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
                    select(RightsRelease)
                    .where(RightsRelease.project_id == project_id)
                    .order_by(
                        RightsRelease.subject_type,
                        RightsRelease.subject_id,
                        RightsRelease.version.desc(),
                    )
                )
            )
            return [_rights_release_read(item) for item in releases]

    async def revoke_rights_release(
        self,
        workspace_id: UUID,
        release_id: UUID,
        actor_id: UUID,
        reason: str,
        expected_state_version: int,
    ) -> RightsReleaseRead:
        async with self._sessions.begin() as session:
            release = await _locked_rights_release(session, workspace_id, release_id)
            if release.state_version != expected_state_version:
                raise RightsReleaseConflictError("rights release state version mismatch")
            if release.status != "ACTIVE" or release.revoked_at is not None:
                raise RightsReleaseConflictError("rights release is already revoked")
            release.status = "REVOKED"
            release.state_version += 1
            release.revoked_at = datetime.now(UTC)
            release.revoked_by = actor_id
            release.revocation_reason = reason
            session.add(
                OutboxEvent(
                    workspace_id=workspace_id,
                    aggregate_type="rights_release",
                    aggregate_id=release.id,
                    event_type="rights_release.revoked",
                    payload={"release_id": str(release.id), "reason": reason},
                )
            )
            await session.flush()
            return _rights_release_read(release)

    async def check_rights_release(
        self, workspace_id: UUID, release_id: UUID, request: RightsExecutionCheck
    ) -> RightsExecutionDecision:
        async with self._sessions() as session:
            release = await session.scalar(
                select(RightsRelease)
                .join(Project, Project.id == RightsRelease.project_id)
                .where(
                    RightsRelease.id == release_id,
                    Project.workspace_id == workspace_id,
                )
            )
            if release is None:
                raise ProjectNotFoundError(release_id)
            return evaluate_rights_release(_rights_release_read(release), request)

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

    async def list_analysis_documents(
        self,
        workspace_id: UUID,
        project_id: UUID,
        episode_id: UUID | None = None,
        document_type: str | None = None,
    ) -> list[AnalysisDocumentRead]:
        async with self._sessions() as session:
            exists = await session.scalar(
                select(Project.id).where(
                    Project.id == project_id, Project.workspace_id == workspace_id
                )
            )
            if exists is None:
                raise ProjectNotFoundError(project_id)
            query = select(AnalysisDocument).where(AnalysisDocument.project_id == project_id)
            if episode_id is not None:
                query = query.where(AnalysisDocument.episode_id == episode_id)
            if document_type is not None:
                query = query.where(AnalysisDocument.document_type == document_type)
            documents = list(
                await session.scalars(query.order_by(AnalysisDocument.created_at.desc()))
            )
            return [_analysis_document_read(document) for document in documents]

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


def _analysis_document_read(document: AnalysisDocument) -> AnalysisDocumentRead:
    return AnalysisDocumentRead(
        id=document.id,
        project_id=document.project_id,
        episode_id=document.episode_id,
        source_stage_run_id=document.source_stage_run_id,
        media_asset_id=document.media_asset_id,
        document_type=document.document_type,
        schema_version=document.schema_version,
        payload=document.payload,
        created_at=document.created_at,
        updated_at=document.updated_at,
    )


async def _locked_rights_release(
    session: AsyncSession, workspace_id: UUID, release_id: UUID
) -> RightsRelease:
    release = await session.scalar(
        select(RightsRelease)
        .join(Project, Project.id == RightsRelease.project_id)
        .where(RightsRelease.id == release_id, Project.workspace_id == workspace_id)
        .with_for_update()
    )
    if release is None:
        raise ProjectNotFoundError(release_id)
    return release


def _rights_release_read(release: RightsRelease) -> RightsReleaseRead:
    return RightsReleaseRead(
        id=release.id,
        project_id=release.project_id,
        subject_type=release.subject_type,
        subject_id=release.subject_id,
        version=release.version,
        status=release.status,
        state_version=release.state_version,
        allowed_operations=frozenset(release.allowed_operations),
        allowed_markets=frozenset(release.allowed_markets),
        allowed_languages=frozenset(release.allowed_languages),
        commercial_scope=release.commercial_scope,
        valid_from=release.valid_from,
        expires_at=release.expires_at,
        revoked_at=release.revoked_at,
        revoked_by=release.revoked_by,
        revocation_reason=release.revocation_reason,
        minor_guardian_consent=release.minor_guardian_consent,
        source_asset_ids=tuple(UUID(value) for value in release.source_asset_ids),
        evidence_uri=release.evidence_uri,
        evidence_sha256=release.evidence_sha256,
        supersedes_release_id=release.supersedes_release_id,
        created_by=release.created_by,
        created_at=release.created_at,
        updated_at=release.updated_at,
    )


def _build_tts_request(
    item: DubbingUtteranceCreate,
    *,
    target_market: str,
    localization_release_id: UUID,
    voice_release_id: UUID,
    voice_reference_sha256: str,
    rights: RightsReleaseRead,
    selected_model_release: str,
    commercial_use: bool,
) -> TtsRequest:
    utterance = Utterance(
        utterance_id=item.utterance_id,
        character_id=item.character_id,
        source_text=item.source_text,
        source_language=item.source_language,
        start_seconds=item.start_seconds,
        end_seconds=item.end_seconds,
        emotion=item.emotion,
        protected_terms=item.protected_terms,
    )
    localized = LocalizedUtterance(
        utterance=utterance,
        target_text=item.target_text,
        target_language=item.target_language,
        target_market=target_market,
        localization_release=str(localization_release_id),
        review_state=ReviewState.HUMAN_APPROVED,
        semantic_entity_ids=item.semantic_entity_ids,
    )
    snapshot = VoiceRightsSnapshot(
        rights_release_id=rights.id,
        state_version=rights.state_version,
        subject_id=rights.subject_id,
        allowed_operations=rights.allowed_operations,
        allowed_languages=rights.allowed_languages,
        allowed_markets=rights.allowed_markets,
        commercial_allowed=rights.commercial_scope == "COMMERCIAL",
        valid_at_execution=True,
    )
    voice = VoiceRelease(
        voice_release_id=voice_release_id,
        character_id=item.character_id,
        model_release=selected_model_release,
        reference_asset_sha256s=(voice_reference_sha256,),
        rights=snapshot,
    )
    return TtsRequest(
        localized=localized,
        voice_release=voice,
        seed=item.seed,
        speed=item.speed,
        candidate_count=item.candidate_count,
        commercial_use=commercial_use,
    )


async def _candidate_variant_read(
    session: AsyncSession, variant: RenderVariant
) -> CandidateVariantRead:
    metrics = list(
        await session.scalars(
            select(QcResult)
            .where(QcResult.render_variant_id == variant.id)
            .order_by(QcResult.metric_name, QcResult.metric_version)
        )
    )
    return CandidateVariantRead(
        id=variant.id,
        candidate_group_id=variant.candidate_group_id,
        stage_run_id=variant.stage_run_id,
        variant_no=variant.variant_no,
        status=variant.status,
        seed=variant.seed,
        output_asset_id=variant.output_asset_id,
        raw_metrics=variant.raw_metrics,
        allocated_cost=variant.allocated_cost,
        qc_results=tuple(
            QcMetricRead(
                id=item.id,
                metric_name=item.metric_name,
                metric_version=item.metric_version,
                evaluator_release=item.evaluator_release,
                score=item.score,
                verdict=item.verdict,
                hard_failure=item.hard_failure,
                details=item.details,
                created_at=item.created_at,
            )
            for item in metrics
        ),
        created_at=variant.created_at,
        updated_at=variant.updated_at,
    )


async def _candidate_group_read(
    session: AsyncSession, group: CandidateGroup
) -> CandidateGroupRead:
    variants = list(
        await session.scalars(
            select(RenderVariant)
            .where(RenderVariant.candidate_group_id == group.id)
            .order_by(RenderVariant.stage_run_id, RenderVariant.variant_no)
        )
    )
    return CandidateGroupRead(
        id=group.id,
        project_id=group.project_id,
        shot_id=group.shot_id,
        purpose=group.purpose,
        status=group.status,
        state_version=group.state_version,
        adopted_variant_id=group.adopted_variant_id,
        variants=tuple(
            [await _candidate_variant_read(session, item) for item in variants]
        ),
        created_at=group.created_at,
        updated_at=group.updated_at,
    )


async def _stage_rights_failure(
    session: AsyncSession, run: StageRun
) -> str | None:
    if run.stage_type not in {"TTS_GENERATE", "LIPSYNC_GENERATE"}:
        return None
    try:
        if run.stage_type == "TTS_GENERATE":
            request = run.params["tts_request"]
            snapshot = request["voice_release"]["rights"]
            market = request["localized"]["target_market"]
            language = request["localized"]["target_language"]
            operation = "voice_clone"
        else:
            request = run.params["lipsync_request"]
            snapshot = request["rights"]
            market = request["target_market"]
            language = request["target_language"]
            operation = "lipsync"
        rights_id = UUID(snapshot["rights_release_id"])
        expected_version = int(run.params["rights_state_version"])
        if int(snapshot["state_version"]) != expected_version:
            return "RIGHTS_SNAPSHOT_VERSION_MISMATCH"
    except (KeyError, TypeError, ValueError):
        return "RIGHTS_SNAPSHOT_INVALID"
    release = await session.scalar(
        select(RightsRelease)
        .where(
            RightsRelease.id == rights_id,
            RightsRelease.project_id == run.project_id,
        )
        .with_for_update()
    )
    if release is None:
        return "RIGHTS_RELEASE_MISSING"
    if release.state_version != expected_version:
        return "RIGHTS_STATE_CHANGED"
    decision = evaluate_rights_release(
        _rights_release_read(release),
        RightsExecutionCheck(
            operation=operation,
            market=str(market),
            language=str(language),
            commercial_use=bool(request.get("commercial_use", True)),
        ),
    )
    return None if decision.allowed else ",".join(decision.reason_codes)


async def _locked_model_release(
    session: AsyncSession, workspace_id: UUID, release_id: UUID
) -> ModelRelease:
    release = await session.scalar(
        select(ModelRelease)
        .where(ModelRelease.id == release_id, ModelRelease.workspace_id == workspace_id)
        .with_for_update()
    )
    if release is None:
        raise ProjectNotFoundError(release_id)
    return release


def _model_release_state(release: ModelRelease) -> ModelReleaseState:
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


def _apply_model_release_state(release: ModelRelease, state: ModelReleaseState) -> None:
    release.license_status = state.license_status
    release.automation_status = state.automation_status
    release.traffic_percent = state.traffic_percent
    release.state_version = state.state_version
    release.reviewed_by = state.reviewed_by
    release.reviewed_at = state.reviewed_at


def _model_release_read(release: ModelRelease) -> ModelReleaseRead:
    return ModelReleaseRead(
        id=release.id,
        workspace_id=release.workspace_id,
        model_key=release.model_key,
        release_name=release.release_name,
        provider=release.provider,
        endpoint=release.endpoint,
        license_id=release.license_id,
        license_status=release.license_status,
        automation_status=release.automation_status,
        traffic_percent=release.traffic_percent,
        state_version=release.state_version,
        model_card_uri=release.model_card_uri,
        config=release.config_json,
        fallback_release_id=release.fallback_release_id,
        reviewed_by=release.reviewed_by,
        reviewed_at=release.reviewed_at,
        approved_benchmark_release_id=release.approved_benchmark_release_id,
        created_at=release.created_at,
        updated_at=release.updated_at,
    )


def _benchmark_release_read(release: BenchmarkRelease) -> BenchmarkReleaseRead:
    return BenchmarkReleaseRead(
        id=release.id,
        workspace_id=release.workspace_id,
        model_release_id=release.model_release_id,
        dataset_key=release.dataset_key,
        dataset_release=release.dataset_release,
        dataset_fingerprint=release.dataset_fingerprint,
        annotation_release=release.annotation_release,
        policy_key=release.policy_key,
        policy_release=release.policy_release,
        policy_fingerprint=release.policy_fingerprint,
        weights_sha256=release.weights_sha256,
        runtime_fingerprint=release.runtime_fingerprint,
        report=release.report,
        approved=release.approved,
        failed_gates=tuple(release.failed_gates),
        created_at=release.created_at,
    )


def _add_model_release_event(
    session: AsyncSession,
    workspace_id: UUID,
    release: ModelRelease,
    event_type: str,
) -> None:
    session.add(
        OutboxEvent(
            workspace_id=workspace_id,
            aggregate_type="model_release",
            aggregate_id=release.id,
            event_type=event_type,
            payload={
                "release_id": str(release.id),
                "model_key": release.model_key,
                "license_status": str(release.license_status),
                "automation_status": str(release.automation_status),
                "traffic_percent": release.traffic_percent,
            },
        )
    )


async def _select_model_release(
    session: AsyncSession,
    workspace_id: UUID,
    model_key: str,
    job_id: UUID,
) -> ModelRelease | None:
    candidates = list(
        await session.scalars(
            select(ModelRelease)
            .where(
                ModelRelease.workspace_id == workspace_id,
                ModelRelease.model_key == model_key,
                ModelRelease.license_status == "APPROVED",
                ModelRelease.automation_status.in_(("CANARY", "ACTIVE")),
            )
            .with_for_update()
        )
    )
    if not candidates:
        return None
    active = [item for item in candidates if item.automation_status == "ACTIVE"]
    canary = [item for item in candidates if item.automation_status == "CANARY"]
    if len(active) > 1 or len(canary) > 1:
        raise ModelReleaseConflictError(f"conflicting traffic releases exist for {model_key}")
    if canary and canary_receives_job(job_id, model_key, canary[0].traffic_percent):
        return canary[0]
    return active[0] if active else None


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
