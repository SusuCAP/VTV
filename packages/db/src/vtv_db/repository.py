from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Protocol
from uuid import UUID, uuid4

from pydantic import BaseModel
from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from vtv_delivery import (
    ApprovalEvidence,
    CostSummary,
    DeliveredAsset,
    DeliveryApprove,
    DeliveryCreate,
    DeliveryManifestBuilder,
    DeliveryPackage,
    DeliveryPackageAsset,
    DeliveryRead,
    DeliveryRevoke,
    EditStageEvidence,
    ModelEvidence,
    QcEvidence,
    ShotDeliveryEntry,
)
from vtv_evaluation import evaluate_release
from vtv_evaluation.contracts import (
    EvaluatorReleaseCreate,
    EvaluatorReleaseRead,
    QcEvidenceCreate,
)
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
from vtv_routing.contracts import EpisodeWorkflowPlan
from vtv_schemas.analysis import AnalysisDocumentRead
from vtv_schemas.assembly import EpisodeAssemblyJobCreate
from vtv_schemas.benchmarks import BenchmarkReleaseCreate, BenchmarkReleaseRead
from vtv_schemas.candidates import (
    CandidateAdopt,
    CandidateGroupRead,
    CandidateQcCreate,
    CandidateVariantRead,
    QcMetricRead,
)
from vtv_schemas.cost_report import ModelCostEntry, ProjectCostReport, StageCostEntry
from vtv_schemas.enums import JobStatus, ProjectStatus
from vtv_schemas.episodes import EpisodeRead
from vtv_schemas.jobs import JobProgress, JobRead, JobSummary, ProduceRequest
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
    Delivery,
    DeliveryAsset,
    Episode,
    EvaluatorRelease,
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
    StageAttempt,
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


class DeliveryConflictError(ValueError):
    pass


class StageNotReadyError(ValueError):
    pass


class EvaluatorConflictError(ValueError):
    pass


class StageRunRead(BaseModel):
    id: UUID
    project_id: UUID
    job_id: UUID | None
    episode_id: UUID | None
    shot_id: UUID | None
    stage_type: str
    status: str
    state_version: int
    created_at: datetime
    updated_at: datetime


class FailedStageRead(BaseModel):
    stage_run_id: UUID
    stage_type: str
    episode_id: UUID | None
    shot_id: UUID | None
    status: str
    error_class: str | None
    error_detail: dict | None
    attempt_count: int
    last_attempt_at: datetime | None
    created_at: datetime


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

LOUDNESS_PRESETS = {
    "web-dialogue": {
        "name": "web-dialogue",
        "integrated_lufs": -16,
        "true_peak_dbfs": -1.5,
        "loudness_range_lu": 11,
    },
    "broadcast": {
        "name": "broadcast",
        "integrated_lufs": -24,
        "true_peak_dbfs": -2,
        "loudness_range_lu": 7,
    },
    "mobile": {
        "name": "mobile",
        "integrated_lufs": -14,
        "true_peak_dbfs": -1,
        "loudness_range_lu": 9,
    },
}


def _build_delivery_manifest(
    *,
    delivery_id: UUID,
    workspace_id: UUID,
    project_id: UUID,
    episode_id: UUID,
    project_state_version: int,
    source: dict,
    selected_assets: list[tuple[str, dict]],
    actor_id: str,
    approved_at: datetime,
    c2pa_requested: bool,
) -> dict:
    quality_report = next(asset for role, asset in selected_assets if role == "QUALITY_REPORT")
    shot_list = next(asset for role, asset in selected_assets if role == "SHOT_LIST")
    quality_metadata = quality_report.get("metadata", {})
    shot_metadata = shot_list.get("metadata", {})
    try:
        edit_chain = tuple(
            EditStageEvidence.model_validate(value)
            for value in quality_metadata["edit_chain"]
        )
        models = tuple(
            ModelEvidence.model_validate(value)
            for value in quality_metadata.get("models", [])
        )
        qc = tuple(QcEvidence.model_validate(value) for value in quality_metadata["qc"])
        shots = tuple(
            ShotDeliveryEntry.model_validate(value) for value in shot_metadata["shots"]
        )
        cost = CostSummary.model_validate(quality_metadata["cost"])
        final_encoding = dict(quality_metadata["final_encoding"])
    except (KeyError, TypeError, ValueError) as exc:
        raise DeliveryConflictError("delivery evidence metadata is incomplete") from exc

    def delivered_asset(role: str, asset: dict) -> DeliveredAsset:
        return DeliveredAsset(
            asset_id=asset["id"],
            role=role,
            object_uri=asset["object_uri"],
            sha256=asset["sha256"],
            size_bytes=asset["size_bytes"],
            content_type=asset["content_type"],
            metadata=asset.get("metadata", {}),
        )

    manifest = DeliveryManifestBuilder.build(
        delivery_id=delivery_id,
        workspace_id=workspace_id,
        project_id=project_id,
        episode_id=episode_id,
        project_state_version=project_state_version,
        generated_at=approved_at,
        assets=(
            delivered_asset("SOURCE_VIDEO", source),
            *(delivered_asset(role, asset) for role, asset in selected_assets),
        ),
        edit_chain=edit_chain,
        models=models,
        approvals=(
            ApprovalEvidence(
                subject_type="DELIVERY",
                subject_id=delivery_id,
                decision="APPROVED",
                actor_id=actor_id,
                state_version=1,
                decided_at=approved_at,
            ),
        ),
        qc=qc,
        shots=shots,
        cost=cost,
        final_encoding=final_encoding,
        c2pa_status="PENDING" if c2pa_requested else "NOT_REQUESTED",
    )
    return manifest.model_dump(mode="json")


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

    async def create_episode_assembly_job(
        self, workspace_id: UUID, project_id: UUID, payload: EpisodeAssemblyJobCreate
    ) -> JobRead: ...

    async def create_delivery(
        self, workspace_id: UUID, project_id: UUID, payload: DeliveryCreate
    ) -> DeliveryRead: ...

    async def list_deliveries(
        self, workspace_id: UUID, project_id: UUID, episode_id: UUID | None = None
    ) -> list[DeliveryRead]: ...

    async def get_delivery(
        self, workspace_id: UUID, delivery_id: UUID
    ) -> DeliveryRead: ...

    async def approve_delivery(
        self, workspace_id: UUID, delivery_id: UUID, payload: DeliveryApprove
    ) -> DeliveryRead: ...

    async def request_c2pa_signing(
        self, workspace_id: UUID, delivery_id: UUID
    ) -> DeliveryRead: ...

    async def complete_c2pa_signing(
        self,
        workspace_id: UUID,
        delivery_id: UUID,
        success: bool,
        credential_uri: str | None = None,
    ) -> DeliveryRead: ...

    async def get_delivery_package(
        self, workspace_id: UUID, delivery_id: UUID
    ) -> DeliveryPackage: ...

    async def revoke_delivery(
        self, workspace_id: UUID, delivery_id: UUID, payload: DeliveryRevoke
    ) -> DeliveryRead: ...

    async def list_job_summaries(
        self, workspace_id: UUID, project_id: UUID
    ) -> list[JobSummary]: ...

    async def get_job_progress(
        self, workspace_id: UUID, project_id: UUID, job_id: UUID
    ) -> JobProgress: ...

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

    async def create_production_job(
        self, workspace_id: UUID, project_id: UUID, payload: ProduceRequest
    ) -> JobRead: ...

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

    async def retry_stage(
        self,
        workspace_id: UUID,
        project_id: UUID,
        stage_run_id: UUID,
        reason: str,
    ) -> StageRunRead: ...

    async def override_shot_route(
        self,
        workspace_id: UUID,
        project_id: UUID,
        shot_id: UUID,
        route: str,
        reason: str,
        force_rerun: bool,
    ) -> dict: ...

    async def list_failed_stages(
        self,
        workspace_id: UUID,
        project_id: UUID,
        stage_type: str | None = None,
        episode_id: UUID | None = None,
        status: str = "EXECUTION_FAILED",
    ) -> list[FailedStageRead]: ...

    async def create_evaluator_release(
        self, workspace_id: UUID, payload: EvaluatorReleaseCreate
    ) -> EvaluatorReleaseRead: ...

    async def list_evaluator_releases(
        self, workspace_id: UUID, evaluator_key: str | None = None
    ) -> list[EvaluatorReleaseRead]: ...

    async def get_active_evaluator(
        self, workspace_id: UUID, evaluator_key: str
    ) -> EvaluatorReleaseRead: ...

    async def deprecate_evaluator_release(
        self, workspace_id: UUID, evaluator_release_id: UUID
    ) -> EvaluatorReleaseRead: ...

    async def get_evaluator_release(
        self, workspace_id: UUID, evaluator_release_id: UUID
    ) -> EvaluatorReleaseRead: ...

    async def submit_qc_evidence(
        self, workspace_id: UUID, project_id: UUID, payload: QcEvidenceCreate
    ) -> None: ...

    async def get_project_qc_stats(
        self, workspace_id: UUID, project_id: UUID
    ) -> dict: ...

    async def list_expired_assets(
        self, workspace_id: UUID, project_id: UUID, policy: object
    ) -> list[dict]: ...

    async def cleanup_expired_orphans(
        self, workspace_id: UUID, project_id: UUID | None = None
    ) -> int: ...

    async def get_project_cost_report(
        self, workspace_id: UUID, project_id: UUID
    ) -> ProjectCostReport: ...


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

    async def create_production_job(
        self, workspace_id: UUID, project_id: UUID, payload: ProduceRequest
    ) -> JobRead:
        _ROUTE_TO_STAGE: dict[str, str] = {
            "B": "VISUAL_SUBTITLE_CLEAN",
            "C": "VISUAL_CHARACTER_REPLACE",
            "D": "VISUAL_BACKGROUND_REPLACE",
            "E": "VISUAL_JOINT_REPLACE",
            "F": "VISUAL_FULL_REGEN",
        }
        include_routes: set[str] = (
            set(payload.include_routes) if payload.include_routes else {"B", "C", "D", "E", "F"}
        )

        async with self._sessions.begin() as session:
            project = await session.scalar(
                select(Project)
                .where(Project.id == project_id, Project.workspace_id == workspace_id)
                .with_for_update()
            )
            if project is None:
                raise ProjectNotFoundError(project_id)
            if project.state_version != payload.expected_project_state_version:
                raise ProductionNotReadyError(
                    f"project state version mismatch: "
                    f"expected {payload.expected_project_state_version}, "
                    f"actual {project.state_version}"
                )
            control = await session.get(ExecutionControl, project_id)
            if control is None:
                raise RuntimeError("project execution control is missing")
            episodes = list(
                await session.scalars(
                    select(Episode)
                    .where(
                        Episode.project_id == project_id,
                        Episode.source_asset_id.is_not(None),
                    )
                    .order_by(Episode.episode_no)
                    .with_for_update()
                )
            )
            if not episodes:
                raise ProductionNotReadyError(
                    "visual production requires at least one uploaded episode"
                )

            # Resolve WORKFLOW_PLAN per episode
            episode_plans: dict[UUID, EpisodeWorkflowPlan | None] = {}
            for episode in episodes:
                doc = await session.scalar(
                    select(AnalysisDocument)
                    .where(
                        AnalysisDocument.project_id == project_id,
                        AnalysisDocument.episode_id == episode.id,
                        AnalysisDocument.document_type == "WORKFLOW_PLAN",
                    )
                    .order_by(AnalysisDocument.created_at.desc())
                    .limit(1)
                )
                episode_plans[episode.id] = (
                    EpisodeWorkflowPlan.model_validate(doc.payload) if doc is not None else None
                )

            # Gather all non-A shots that will be processed (for ratio check)
            planned_shots: list[tuple[UUID, str]] = []  # (shot_id, effective_route)
            for episode in episodes:
                plan = episode_plans[episode.id]
                if plan is None:
                    continue
                for decision in plan.decisions:
                    route = payload.shot_route_overrides.get(
                        str(decision.shot_id), str(decision.route)
                    )
                    if route == "A" or route not in include_routes:
                        continue
                    planned_shots.append((decision.shot_id, route))

            # Enforce max_full_regen_ratio gate
            if planned_shots:
                full_regen_count = sum(1 for _, r in planned_shots if r == "F")
                if full_regen_count / len(planned_shots) > payload.max_full_regen_ratio:
                    raise ProductionNotReadyError(
                        f"FULL_REGEN shot count {full_regen_count} of {len(planned_shots)} "
                        f"exceeds max_full_regen_ratio {payload.max_full_regen_ratio}"
                    )

            # Batch-load shots to get expected_duration_seconds for VISUAL_QC params
            all_shot_ids = [
                d.shot_id
                for ep in episodes
                for d in (episode_plans[ep.id].decisions if episode_plans[ep.id] else [])
            ]
            shots_by_id: dict[UUID, Shot] = {}
            if all_shot_ids:
                shot_rows = list(
                    await session.scalars(select(Shot).where(Shot.id.in_(all_shot_ids)))
                )
                shots_by_id = {s.id: s for s in shot_rows}

            # Pre-compute total_stages
            total_stages = 0
            for episode in episodes:
                plan = episode_plans[episode.id]
                if plan is None:
                    total_stages += 1  # SHOT_ROUTING
                else:
                    for decision in plan.decisions:
                        route = payload.shot_route_overrides.get(
                            str(decision.shot_id), str(decision.route)
                        )
                        if route != "A" and route in include_routes:
                            total_stages += 3  # VISUAL_KEYFRAME_PREVIEW + route stage + VISUAL_QC

            job = Job(
                id=self._id_factory(),
                project_id=project_id,
                kind="VISUAL_PRODUCTION",
                status=JobStatus.QUEUED,
                idempotency_key=f"visual-production:{payload.expected_project_state_version}",
                total_stages=total_stages,
            )
            session.add(job)

            # Build stage runs; track triplets (kf_id, rt_run, qc_run) for dependency wiring
            dep_triplets: list[tuple[UUID, StageRun, StageRun]] = []

            for episode in episodes:
                plan = episode_plans[episode.id]
                if plan is None:
                    session.add(
                        StageRun(
                            id=self._id_factory(),
                            job_id=job.id,
                            project_id=project_id,
                            episode_id=episode.id,
                            stage_type="SHOT_ROUTING",
                            status="READY",
                            idempotency_key=f"{job.id}:shot_routing:{episode.id}",
                            runtime_profile_id="cpu-standard",
                            observed_control_version=control.control_version,
                            params={
                                "episode_id": str(episode.id),
                                "source_asset_id": str(episode.source_asset_id),
                            },
                        )
                    )
                else:
                    for decision in plan.decisions:
                        route = payload.shot_route_overrides.get(
                            str(decision.shot_id), str(decision.route)
                        )
                        if route == "A" or route not in include_routes:
                            continue
                        stage_type = _ROUTE_TO_STAGE[route]
                        shot_rec = shots_by_id.get(decision.shot_id)
                        expected_duration = (
                            (shot_rec.end_ms - shot_rec.start_ms) / 1000.0
                            if shot_rec is not None
                            else None
                        )
                        kf_run = StageRun(
                            id=self._id_factory(),
                            job_id=job.id,
                            project_id=project_id,
                            episode_id=episode.id,
                            shot_id=decision.shot_id,
                            stage_type="VISUAL_KEYFRAME_PREVIEW",
                            status="READY",
                            idempotency_key=f"{job.id}:keyframe_preview:{decision.shot_id}",
                            runtime_profile_id="gpu-visual",
                            observed_control_version=control.control_version,
                            params={
                                "shot_id": str(decision.shot_id),
                                "episode_id": str(episode.id),
                            },
                        )
                        session.add(kf_run)
                        rt_run = StageRun(
                            id=self._id_factory(),
                            job_id=job.id,
                            project_id=project_id,
                            episode_id=episode.id,
                            shot_id=decision.shot_id,
                            stage_type=stage_type,
                            status="PENDING",
                            idempotency_key=f"{job.id}:{stage_type.lower()}:{decision.shot_id}",
                            runtime_profile_id="gpu-visual",
                            observed_control_version=control.control_version,
                            params={
                                "shot_id": str(decision.shot_id),
                                "episode_id": str(episode.id),
                                "route": route,
                            },
                        )
                        session.add(rt_run)
                        qc_run = StageRun(
                            id=self._id_factory(),
                            job_id=job.id,
                            project_id=project_id,
                            episode_id=episode.id,
                            shot_id=decision.shot_id,
                            stage_type="VISUAL_QC",
                            status="PENDING",
                            idempotency_key=f"{job.id}:visual_qc:{decision.shot_id}",
                            runtime_profile_id="cpu-standard",
                            observed_control_version=control.control_version,
                            params={
                                "shot_id": str(decision.shot_id),
                                "episode_id": str(episode.id),
                                "route": route,
                                "visual_qc_request": {
                                    "evaluator_key": "visual_technical",
                                    "route": route,
                                    "expected_duration_seconds": expected_duration,
                                    "hard_failure_below": {
                                        "frame_integrity": 0.5,
                                        "duration_deviation": 0.0,
                                        "audio_stream_present": 0.5,
                                    },
                                    "thresholds": {
                                        "frame_integrity": 0.8,
                                        "duration_deviation": 0.9,
                                        "resolution_match": 0.8,
                                    },
                                },
                            },
                        )
                        session.add(qc_run)
                        dep_triplets.append((kf_run.id, rt_run, qc_run))

            await session.flush()

            for kf_id, rt_run, qc_run in dep_triplets:
                session.add(
                    StageDependency(
                        stage_run_id=rt_run.id,
                        depends_on_stage_run_id=kf_id,
                    )
                )
                session.add(
                    StageDependency(
                        stage_run_id=qc_run.id,
                        depends_on_stage_run_id=rt_run.id,
                    )
                )

            project.state_version += 1
            session.add(
                OutboxEvent(
                    workspace_id=workspace_id,
                    aggregate_type="job",
                    aggregate_id=job.id,
                    event_type="production_job.created",
                    payload={
                        "job_id": str(job.id),
                        "project_id": str(project_id),
                        "episode_ids": [str(ep.id) for ep in episodes],
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

    async def create_episode_assembly_job(
        self, workspace_id: UUID, project_id: UUID, payload: EpisodeAssemblyJobCreate
    ) -> JobRead:
        async with self._sessions.begin() as session:
            project = await session.scalar(
                select(Project)
                .where(Project.id == project_id, Project.workspace_id == workspace_id)
                .with_for_update()
            )
            if project is None:
                raise ProjectNotFoundError(project_id)
            idempotency_key = f"episode-assembly:{payload.fingerprint}"
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
            source = await session.scalar(
                select(MediaAsset).where(
                    MediaAsset.id == payload.source_video_asset_id,
                    MediaAsset.workspace_id == workspace_id,
                    MediaAsset.project_id == project_id,
                )
            )
            if (
                source is None
                or not source.content_type.startswith("video/")
                or source.metadata_json.get("episode_id") != str(episode.id)
            ):
                raise ProductionNotReadyError(
                    "assembly source must be a video asset bound to the requested episode"
                )
            duration = source.metadata_json.get("duration_seconds")
            if not isinstance(duration, (int, float)) or duration <= 0:
                raise ProductionNotReadyError(
                    "assembly source requires authoritative duration_seconds metadata"
                )
            duration = float(duration)
            picture_assets: list[MediaAsset] = []
            picture_edits: list[dict] = []
            previous_end = 0.0
            selections = sorted(
                payload.picture_selections,
                key=lambda item: str(item.shot_id),
            )
            resolved_pictures: list[tuple[Shot, RenderVariant, MediaAsset]] = []
            for item in selections:
                row = (
                    await session.execute(
                        select(Shot, RenderVariant, MediaAsset)
                        .join(CandidateGroup, CandidateGroup.shot_id == Shot.id)
                        .join(
                            RenderVariant,
                            RenderVariant.candidate_group_id == CandidateGroup.id,
                        )
                        .join(MediaAsset, MediaAsset.id == RenderVariant.output_asset_id)
                        .where(
                            Shot.id == item.shot_id,
                            Shot.episode_id == episode.id,
                            RenderVariant.id == item.adopted_variant_id,
                            RenderVariant.status == "ADOPTED",
                            CandidateGroup.project_id == project_id,
                            CandidateGroup.purpose.in_(("LIPSYNC", "RENDER")),
                            CandidateGroup.adopted_variant_id == RenderVariant.id,
                            MediaAsset.workspace_id == workspace_id,
                            MediaAsset.content_type.like("video/%"),
                        )
                    )
                ).one_or_none()
                if row is None:
                    raise ProductionNotReadyError(
                        "picture conform requires adopted same-episode video variants"
                    )
                resolved_pictures.append(row)
            for shot, _variant, asset in sorted(
                resolved_pictures, key=lambda row: row[0].start_ms
            ):
                start = shot.start_ms / 1000
                end = shot.end_ms / 1000
                if start < previous_end or end > duration + 0.05:
                    raise ProductionNotReadyError(
                        "adopted picture shot intervals overlap or exceed episode duration"
                    )
                previous_end = end
                picture_assets.append(asset)
                picture_edits.append(
                    {
                        "shot_id": str(shot.id),
                        "replacement_sha256": asset.sha256,
                        "start_seconds": start,
                        "end_seconds": end,
                    }
                )
            dialogue_assets: list[MediaAsset] = []
            mix_tracks: list[dict] = []
            for item in payload.dialogue_selections:
                row = (
                    await session.execute(
                        select(RenderVariant, CandidateGroup, StageRun, MediaAsset)
                        .join(
                            CandidateGroup,
                            CandidateGroup.id == RenderVariant.candidate_group_id,
                        )
                        .join(StageRun, StageRun.id == RenderVariant.stage_run_id)
                        .join(MediaAsset, MediaAsset.id == RenderVariant.output_asset_id)
                        .where(
                            RenderVariant.id == item.adopted_variant_id,
                            RenderVariant.status == "ADOPTED",
                            CandidateGroup.project_id == project_id,
                            CandidateGroup.purpose == "TTS",
                            CandidateGroup.adopted_variant_id == RenderVariant.id,
                            StageRun.episode_id == episode.id,
                            MediaAsset.workspace_id == workspace_id,
                            MediaAsset.content_type.like("audio/%"),
                        )
                    )
                ).one_or_none()
                if row is None:
                    raise ProductionNotReadyError(
                        "audio mix requires adopted same-episode TTS variants"
                    )
                variant, _, run, asset = row
                try:
                    utterance = run.params["tts_request"]["localized"]["utterance"]
                    start = float(utterance["start_seconds"])
                    end = float(utterance["end_seconds"])
                except (KeyError, TypeError, ValueError) as exc:
                    raise ProductionNotReadyError(
                        "adopted TTS variant has invalid timeline provenance"
                    ) from exc
                if start < 0 or end <= start or end > duration + 0.05:
                    raise ProductionNotReadyError(
                        "adopted TTS timeline exceeds episode duration"
                    )
                dialogue_assets.append(asset)
                mix_tracks.append(
                    {
                        "asset_sha256": asset.sha256,
                        "role": "DIALOGUE",
                        "start_seconds": start,
                        "gain_db": item.gain_db,
                        "room_reverb": item.room_reverb,
                    }
                )
            stem_assets: list[MediaAsset] = []
            for item in payload.stem_selections:
                asset = await session.scalar(
                    select(MediaAsset).where(
                        MediaAsset.id == item.asset_id,
                        MediaAsset.workspace_id == workspace_id,
                        MediaAsset.project_id == project_id,
                        MediaAsset.content_type.like("audio/%"),
                    )
                )
                if (
                    asset is None
                    or asset.metadata_json.get("episode_id") != str(episode.id)
                    or asset.metadata_json.get("stem_kind") != item.role
                ):
                    raise ProductionNotReadyError(
                        "stem asset must match the requested episode and role"
                    )
                stem_assets.append(asset)
                mix_tracks.append(
                    {
                        "asset_sha256": asset.sha256,
                        "role": item.role,
                        "start_seconds": 0,
                        "gain_db": item.gain_db,
                        "room_reverb": 0,
                    }
                )
            subtitle_document = {
                "locale": project.locale,
                "cues": [item.model_dump(mode="json") for item in payload.subtitle_cues],
            }
            if any(item.end_seconds > duration + 0.05 for item in payload.subtitle_cues):
                raise ProductionNotReadyError("subtitle cue exceeds episode duration")
            configured_formats = list(project.output_spec.get("subtitle_formats", ["srt"]))
            sidecar_formats = [item for item in configured_formats if item in {"srt", "vtt"}]
            if payload.burn_subtitles and "srt" not in sidecar_formats:
                sidecar_formats.insert(0, "srt")
            if not sidecar_formats:
                sidecar_formats = ["srt"]
            episode_shots = list(
                await session.scalars(
                    select(Shot)
                    .where(Shot.episode_id == episode.id)
                    .order_by(Shot.shot_no)
                )
            )
            if (
                not episode_shots
                or episode_shots[0].start_ms != 0
                or episode_shots[-1].end_ms != round(duration * 1000)
                or any(
                    previous.end_ms != current.start_ms
                    for previous, current in zip(
                        episode_shots, episode_shots[1:], strict=False
                    )
                )
            ):
                raise ProductionNotReadyError(
                    "delivery shot list must continuously span the full episode"
                )
            selected_by_shot = {
                shot.id: (variant, asset)
                for shot, variant, asset in resolved_pictures
            }
            delivery_shots = []
            for shot in episode_shots:
                selection = selected_by_shot.get(shot.id)
                route = shot.route if shot.route in {"L0", "L1", "L2", "L3", "L4", "L5"} else None
                delivery_shots.append(
                    {
                        "shot_id": str(shot.id),
                        "shot_no": shot.shot_no,
                        "start_ms": shot.start_ms,
                        "end_ms": shot.end_ms,
                        "route": route or ("L2" if selection else "L0"),
                        "adopted_variant_id": str(selection[0].id) if selection else None,
                        "output_asset_id": str(selection[1].id) if selection else None,
                        "qc_verdict": "PASS" if selection else "SOURCE_UNCHANGED",
                    }
                )
            selected_variant_ids = {
                item.adopted_variant_id for item in payload.picture_selections
            } | {
                item.adopted_variant_id for item in payload.dialogue_selections
            }
            qc_rows = list(
                await session.scalars(
                    select(QcResult).where(
                        QcResult.render_variant_id.in_(selected_variant_ids),
                        QcResult.verdict.in_(("PASS", "REVIEW")),
                        QcResult.hard_failure.is_(False),
                    )
                )
            )
            delivery_qc = [
                {
                    "metric_name": item.metric_name,
                    "metric_version": item.metric_version,
                    "evaluator_release": item.evaluator_release,
                    "score": item.score,
                    "verdict": item.verdict,
                    "hard_failure": item.hard_failure,
                }
                for item in qc_rows
            ]
            job = Job(
                id=self._id_factory(),
                project_id=project_id,
                kind="EPISODE_ASSEMBLY",
                status=JobStatus.QUEUED,
                idempotency_key=idempotency_key,
                total_stages=5,
            )
            picture = StageRun(
                id=self._id_factory(),
                job_id=job.id,
                project_id=project_id,
                episode_id=episode.id,
                stage_type="PICTURE_CONFORM",
                status="READY",
                idempotency_key=f"{job.id}:picture-conform",
                runtime_profile_id="cpu-assemble",
                observed_control_version=control.control_version,
                params={
                    "input_asset_ids": [
                        str(source.id),
                        *(str(item.id) for item in picture_assets),
                    ],
                    "picture_conform_request": {
                        "source_video_sha256": source.sha256,
                        "duration_seconds": duration,
                        "edits": picture_edits,
                    },
                },
            )
            subtitle = StageRun(
                id=self._id_factory(),
                job_id=job.id,
                project_id=project_id,
                episode_id=episode.id,
                stage_type="SUBTITLE_RENDER",
                status="READY",
                idempotency_key=f"{job.id}:subtitles",
                runtime_profile_id="cpu-assemble",
                observed_control_version=control.control_version,
                params={
                    "subtitle_document": subtitle_document,
                    "formats": sidecar_formats,
                },
            )
            mix = StageRun(
                id=self._id_factory(),
                job_id=job.id,
                project_id=project_id,
                episode_id=episode.id,
                stage_type="AUDIO_MIX",
                status="READY",
                idempotency_key=f"{job.id}:audio-mix",
                runtime_profile_id="cpu-assemble",
                observed_control_version=control.control_version,
                params={
                    "input_asset_ids": [
                        *(str(item.id) for item in dialogue_assets),
                        *(str(item.id) for item in stem_assets),
                    ],
                    "audio_mix_request": {
                        "duration_seconds": duration,
                        "tracks": mix_tracks,
                        "preset": LOUDNESS_PRESETS[payload.loudness_preset],
                        "sample_rate": 48_000,
                        "channels": 2,
                    },
                },
            )
            output = project.output_spec
            master = StageRun(
                id=self._id_factory(),
                job_id=job.id,
                project_id=project_id,
                episode_id=episode.id,
                stage_type="ASSEMBLE_EPISODE",
                status="PENDING",
                idempotency_key=f"{job.id}:master",
                runtime_profile_id="cpu-assemble",
                observed_control_version=control.control_version,
                params={
                    "episode_assembly_template": {
                        "duration_seconds": duration,
                        "width": output["width"],
                        "height": output["height"],
                        "fps": output["fps"],
                        "video_codec": output["video_codec"],
                        "audio_codec": output["audio_codec"],
                        "burn_subtitles": payload.burn_subtitles,
                        "subtitle_document": subtitle_document,
                    }
                },
            )
            evidence = StageRun(
                id=self._id_factory(),
                job_id=job.id,
                project_id=project_id,
                episode_id=episode.id,
                stage_type="DELIVERY_EVIDENCE",
                status="PENDING",
                idempotency_key=f"{job.id}:delivery-evidence",
                runtime_profile_id="cpu-assemble",
                observed_control_version=control.control_version,
                params={
                    "delivery_evidence_template": {
                        "source_video_sha256": source.sha256,
                        "project_state_version": project.state_version + 1,
                        "duration_ms": round(duration * 1000),
                        "shots": delivery_shots,
                        "qc": delivery_qc,
                    }
                },
            )
            session.add(job)
            session.add_all((picture, subtitle, mix, master, evidence))
            session.add_all(
                (
                    StageDependency(
                        stage_run_id=master.id,
                        depends_on_stage_run_id=picture.id,
                    ),
                    StageDependency(
                        stage_run_id=master.id,
                        depends_on_stage_run_id=subtitle.id,
                    ),
                    StageDependency(
                        stage_run_id=master.id,
                        depends_on_stage_run_id=mix.id,
                    ),
                    StageDependency(
                        stage_run_id=evidence.id,
                        depends_on_stage_run_id=master.id,
                    ),
                )
            )
            project.status = ProjectStatus.PRODUCING
            project.state_version += 1
            session.add(
                OutboxEvent(
                    workspace_id=workspace_id,
                    aggregate_type="job",
                    aggregate_id=job.id,
                    event_type="assembly.requested",
                    payload={
                        "job_id": str(job.id),
                        "project_id": str(project_id),
                        "episode_id": str(episode.id),
                        "picture_edit_count": len(picture_edits),
                        "dialogue_track_count": len(dialogue_assets),
                        "stem_count": len(stem_assets),
                    },
                )
            )
            await session.flush()
            return _job_read(job)

    async def create_delivery(
        self, workspace_id: UUID, project_id: UUID, payload: DeliveryCreate
    ) -> DeliveryRead:
        async with self._sessions.begin() as session:
            project = await session.scalar(
                select(Project)
                .where(Project.id == project_id, Project.workspace_id == workspace_id)
                .with_for_update()
            )
            if project is None:
                raise ProjectNotFoundError(project_id)
            if project.state_version != payload.expected_project_state_version:
                raise DeliveryConflictError(
                    "project state version mismatch: "
                    f"expected {payload.expected_project_state_version}, "
                    f"actual {project.state_version}"
                )
            episode = await session.scalar(
                select(Episode).where(
                    Episode.id == payload.episode_id,
                    Episode.project_id == project_id,
                )
            )
            if episode is None or episode.source_asset_id is None:
                raise ProjectNotFoundError(payload.episode_id)
            role_by_id: dict[UUID, str] = {
                payload.master_asset_id: "MASTER_VIDEO",
                payload.quality_report_asset_id: "QUALITY_REPORT",
                payload.shot_list_asset_id: "SHOT_LIST",
            }
            requested_ids = set(role_by_id)
            requested_ids.update(payload.subtitle_asset_ids)
            requested_ids.update(payload.additional_asset_ids)
            assets = list(
                await session.scalars(
                    select(MediaAsset).where(
                        MediaAsset.id.in_(requested_ids),
                        MediaAsset.workspace_id == workspace_id,
                        MediaAsset.project_id == project_id,
                    )
                )
            )
            if {asset.id for asset in assets} != requested_ids:
                raise ProjectNotFoundError("delivery asset")
            asset_by_id = {asset.id: asset for asset in assets}
            subtitle_roles: set[str] = set()
            for asset_id in payload.subtitle_asset_ids:
                asset = asset_by_id[asset_id]
                role = (
                    "SUBTITLE_VTT"
                    if asset.object_uri.lower().endswith(".vtt")
                    else "SUBTITLE_SRT"
                )
                if role in subtitle_roles:
                    raise DeliveryConflictError("subtitle formats must be unique")
                subtitle_roles.add(role)
                role_by_id[asset_id] = role
            allowed_additional = {"POSTER", "TRAILER", "AD_CUT"}
            for asset_id in payload.additional_asset_ids:
                role = asset_by_id[asset_id].metadata_json.get("delivery_role")
                if role not in allowed_additional or role in role_by_id.values():
                    raise DeliveryConflictError("additional asset has invalid delivery role")
                role_by_id[asset_id] = role
            for asset in assets:
                if asset.metadata_json.get("episode_id") != str(episode.id):
                    raise DeliveryConflictError("delivery assets must belong to the episode")
            if not asset_by_id[payload.master_asset_id].content_type.startswith("video/"):
                raise DeliveryConflictError("master asset must be video")
            if not asset_by_id[payload.quality_report_asset_id].content_type.endswith("json"):
                raise DeliveryConflictError("quality report must be JSON")
            if not asset_by_id[payload.shot_list_asset_id].content_type.endswith("json"):
                raise DeliveryConflictError("shot list must be JSON")
            version = int(
                await session.scalar(
                    select(func.coalesce(func.max(Delivery.version), 0) + 1).where(
                        Delivery.episode_id == episode.id
                    )
                )
            )
            delivery = Delivery(
                id=self._id_factory(),
                workspace_id=workspace_id,
                project_id=project_id,
                episode_id=episode.id,
                version=version,
                project_state_version=project.state_version,
                c2pa_requested=payload.c2pa_requested,
            )
            session.add(delivery)
            session.add_all(
                DeliveryAsset(delivery_id=delivery.id, asset_id=asset_id, role=role)
                for asset_id, role in role_by_id.items()
            )
            await session.flush()
            return _delivery_read(delivery)

    async def list_deliveries(
        self, workspace_id: UUID, project_id: UUID, episode_id: UUID | None = None
    ) -> list[DeliveryRead]:
        async with self._sessions() as session:
            statement = select(Delivery).where(
                Delivery.workspace_id == workspace_id,
                Delivery.project_id == project_id,
            )
            if episode_id is not None:
                statement = statement.where(Delivery.episode_id == episode_id)
            rows = await session.scalars(
                statement.order_by(Delivery.episode_id, Delivery.version.desc())
            )
            return [_delivery_read(row) for row in rows]

    async def get_delivery(
        self, workspace_id: UUID, delivery_id: UUID
    ) -> DeliveryRead:
        async with self._sessions() as session:
            delivery = await session.scalar(
                select(Delivery).where(
                    Delivery.id == delivery_id,
                    Delivery.workspace_id == workspace_id,
                )
            )
            if delivery is None:
                raise ProjectNotFoundError(delivery_id)
            return _delivery_read(delivery)

    async def approve_delivery(
        self, workspace_id: UUID, delivery_id: UUID, payload: DeliveryApprove
    ) -> DeliveryRead:
        async with self._sessions.begin() as session:
            delivery = await session.scalar(
                select(Delivery)
                .where(Delivery.id == delivery_id, Delivery.workspace_id == workspace_id)
                .with_for_update()
            )
            if delivery is None:
                raise ProjectNotFoundError(delivery_id)
            if delivery.state_version != payload.expected_state_version:
                raise DeliveryConflictError(
                    "delivery state version mismatch: "
                    f"expected {payload.expected_state_version}, actual {delivery.state_version}"
                )
            if delivery.status != "DRAFT":
                raise DeliveryConflictError("only draft deliveries can be approved")
            project = await session.scalar(
                select(Project)
                .where(
                    Project.id == delivery.project_id,
                    Project.workspace_id == workspace_id,
                )
                .with_for_update()
            )
            episode = await session.get(Episode, delivery.episode_id)
            if project is None or episode is None or episode.source_asset_id is None:
                raise ProjectNotFoundError(delivery.project_id)
            if project.state_version != delivery.project_state_version:
                raise DeliveryConflictError("project changed after delivery draft was created")
            source = await session.scalar(
                select(MediaAsset).where(
                    MediaAsset.id == episode.source_asset_id,
                    MediaAsset.workspace_id == workspace_id,
                    MediaAsset.project_id == delivery.project_id,
                )
            )
            rows = list(
                (
                    await session.execute(
                        select(DeliveryAsset, MediaAsset)
                        .join(MediaAsset, MediaAsset.id == DeliveryAsset.asset_id)
                        .where(DeliveryAsset.delivery_id == delivery.id)
                    )
                ).all()
            )
            if source is None or not rows:
                raise DeliveryConflictError("delivery assets are incomplete")
            approved_at = datetime.now(UTC)
            manifest_json = _build_delivery_manifest(
                delivery_id=delivery.id,
                workspace_id=workspace_id,
                project_id=delivery.project_id,
                episode_id=delivery.episode_id,
                project_state_version=delivery.project_state_version,
                source=_media_asset_record(source),
                selected_assets=[
                    (link.role, _media_asset_record(asset)) for link, asset in rows
                ],
                actor_id=payload.actor_id,
                approved_at=approved_at,
                c2pa_requested=delivery.c2pa_requested,
            )
            manifest = DeliveryManifestBuilder.build(**manifest_json)
            delivery.manifest = manifest_json
            delivery.manifest_fingerprint = manifest.fingerprint
            delivery.status = "APPROVED"
            delivery.state_version += 1
            delivery.approved_by = payload.actor_id
            delivery.approved_at = approved_at
            session.add(
                OutboxEvent(
                    workspace_id=workspace_id,
                    aggregate_type="delivery",
                    aggregate_id=delivery.id,
                    event_type="delivery.approved",
                    payload={
                        "delivery_id": str(delivery.id),
                        "episode_id": str(delivery.episode_id),
                        "manifest_fingerprint": manifest.fingerprint,
                    },
                )
            )
            await session.flush()
            return _delivery_read(delivery)

    async def request_c2pa_signing(
        self, workspace_id: UUID, delivery_id: UUID
    ) -> DeliveryRead:
        async with self._sessions.begin() as session:
            delivery = await session.scalar(
                select(Delivery)
                .where(Delivery.id == delivery_id, Delivery.workspace_id == workspace_id)
                .with_for_update()
            )
            if delivery is None:
                raise ProjectNotFoundError(delivery_id)
            if not delivery.c2pa_requested:
                raise DeliveryConflictError("delivery was not created with c2pa_requested=True")
            if delivery.status != "APPROVED":
                raise DeliveryConflictError("only approved deliveries can be submitted for signing")
            if delivery.c2pa_status not in ("NOT_REQUESTED", "SIGN_FAILED"):
                raise DeliveryConflictError(
                    f"c2pa_status must be NOT_REQUESTED or SIGN_FAILED, got {delivery.c2pa_status}"
                )
            delivery.c2pa_status = "PENDING"
            delivery.state_version += 1
            session.add(
                OutboxEvent(
                    workspace_id=workspace_id,
                    aggregate_type="delivery",
                    aggregate_id=delivery.id,
                    event_type="c2pa.signing_requested",
                    payload={
                        "delivery_id": str(delivery.id),
                        "manifest_fingerprint": delivery.manifest_fingerprint,
                    },
                )
            )
            await session.flush()
            return _delivery_read(delivery)

    async def complete_c2pa_signing(
        self,
        workspace_id: UUID,
        delivery_id: UUID,
        success: bool,
        credential_uri: str | None = None,
    ) -> DeliveryRead:
        async with self._sessions.begin() as session:
            delivery = await session.scalar(
                select(Delivery)
                .where(Delivery.id == delivery_id, Delivery.workspace_id == workspace_id)
                .with_for_update()
            )
            if delivery is None:
                raise ProjectNotFoundError(delivery_id)
            if delivery.c2pa_status != "SIGNING":
                raise DeliveryConflictError(
                    f"c2pa_status must be SIGNING, got {delivery.c2pa_status}"
                )
            if success:
                delivery.c2pa_status = "SIGNED"
                new_c2pa_manifest_status = "EMBEDDED"
            else:
                delivery.c2pa_status = "SIGN_FAILED"
                new_c2pa_manifest_status = "FAILED"
            # Update manifest c2pa_status and recompute fingerprint
            if delivery.manifest is not None:
                manifest_dict = dict(delivery.manifest)
                manifest_dict["c2pa_status"] = new_c2pa_manifest_status
                updated_manifest = DeliveryManifestBuilder.build(**manifest_dict)
                delivery.manifest = updated_manifest.model_dump(mode="json")
                delivery.manifest_fingerprint = updated_manifest.fingerprint
            delivery.state_version += 1
            event_type = "c2pa.signing_completed" if success else "c2pa.signing_failed"
            session.add(
                OutboxEvent(
                    workspace_id=workspace_id,
                    aggregate_type="delivery",
                    aggregate_id=delivery.id,
                    event_type=event_type,
                    payload={
                        "delivery_id": str(delivery.id),
                        "manifest_fingerprint": delivery.manifest_fingerprint,
                        "credential_uri": credential_uri,
                    },
                )
            )
            await session.flush()
            return _delivery_read(delivery)

    async def get_delivery_package(
        self, workspace_id: UUID, delivery_id: UUID
    ) -> DeliveryPackage:
        async with self._sessions() as session:
            delivery = await session.scalar(
                select(Delivery).where(
                    Delivery.id == delivery_id,
                    Delivery.workspace_id == workspace_id,
                )
            )
            if delivery is None:
                raise ProjectNotFoundError(delivery_id)
            if delivery.status != "APPROVED":
                raise DeliveryConflictError(
                    f"only APPROVED deliveries can generate a package, got {delivery.status}"
                )
            rows = list(
                (
                    await session.execute(
                        select(DeliveryAsset, MediaAsset)
                        .join(MediaAsset, MediaAsset.id == DeliveryAsset.asset_id)
                        .where(DeliveryAsset.delivery_id == delivery_id)
                    )
                ).all()
            )
            expires_at = datetime.now(UTC) + timedelta(minutes=15)
            assets = [
                DeliveryPackageAsset(
                    role=link.role,
                    object_uri=asset.object_uri,
                    sha256=asset.sha256,
                    size_bytes=asset.size_bytes,
                    content_type=asset.content_type,
                    download_url=asset.object_uri,  # passthrough — no S3 presigning configured
                )
                for link, asset in rows
            ]
            return DeliveryPackage(
                delivery_id=delivery_id,
                manifest_fingerprint=delivery.manifest_fingerprint or "",
                assets=assets,
                expires_at=expires_at,
            )

    async def revoke_delivery(
        self, workspace_id: UUID, delivery_id: UUID, payload: DeliveryRevoke
    ) -> DeliveryRead:
        async with self._sessions.begin() as session:
            delivery = await session.scalar(
                select(Delivery)
                .where(Delivery.id == delivery_id, Delivery.workspace_id == workspace_id)
                .with_for_update()
            )
            if delivery is None:
                raise ProjectNotFoundError(delivery_id)
            if delivery.status != "APPROVED":
                raise DeliveryConflictError(
                    f"only APPROVED deliveries can be revoked, got {delivery.status}"
                )
            delivery.status = "REVOKED"
            delivery.state_version += 1
            session.add(
                OutboxEvent(
                    workspace_id=workspace_id,
                    aggregate_type="delivery",
                    aggregate_id=delivery.id,
                    event_type="delivery.revoked",
                    payload={
                        "delivery_id": str(delivery.id),
                        "manifest_fingerprint": delivery.manifest_fingerprint,
                        "reason": payload.reason,
                        "actor_id": payload.actor_id,
                    },
                )
            )
            await session.flush()
            return _delivery_read(delivery)

    async def list_job_summaries(
        self, workspace_id: UUID, project_id: UUID
    ) -> list[JobSummary]:
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
            summaries = []
            for job in jobs:
                completed = int(
                    await session.scalar(
                        select(func.count(StageRun.id)).where(
                            StageRun.job_id == job.id,
                            StageRun.status == "COMPLETED",
                        )
                    ) or 0
                )
                failed = int(
                    await session.scalar(
                        select(func.count(StageRun.id)).where(
                            StageRun.job_id == job.id,
                            StageRun.status == "EXECUTION_FAILED",
                        )
                    ) or 0
                )
                total = job.total_stages or 0
                progress_percent = (completed / total * 100) if total else 0.0
                summaries.append(
                    JobSummary(
                        job_id=job.id,
                        kind=job.kind,
                        status=job.status,
                        total_stages=total,
                        completed_stages=completed,
                        failed_stages=failed,
                        progress_percent=progress_percent,
                        created_at=job.created_at,
                        updated_at=job.updated_at,
                    )
                )
            return summaries

    async def get_job_progress(
        self, workspace_id: UUID, project_id: UUID, job_id: UUID
    ) -> JobProgress:
        async with self._sessions() as session:
            job = await session.scalar(
                select(Job)
                .join(Project, Project.id == Job.project_id)
                .where(
                    Job.id == job_id,
                    Job.project_id == project_id,
                    Project.workspace_id == workspace_id,
                )
            )
            if job is None:
                raise ProjectNotFoundError(job_id)
            stage_rows = list(
                await session.scalars(
                    select(StageRun).where(StageRun.job_id == job_id)
                )
            )
            status_counts: dict[str, int] = {}
            for run in stage_rows:
                status_counts[run.status] = status_counts.get(run.status, 0) + 1
            completed = status_counts.get("COMPLETED", 0)
            failed = status_counts.get("EXECUTION_FAILED", 0)
            running = status_counts.get("RUNNING", 0)
            pending = status_counts.get("PENDING", 0) + status_counts.get("READY", 0)
            total = job.total_stages or 0
            progress_percent = (completed / total * 100) if total else 0.0
            recent_runs = sorted(
                [run for run in stage_rows if run.status == "COMPLETED"],
                key=lambda r: r.updated_at,
                reverse=True,
            )[:5]
            recent_completions = [
                {"stage_type": run.stage_type, "completed_at": run.updated_at.isoformat()}
                for run in recent_runs
            ]
            return JobProgress(
                job_id=job_id,
                status=job.status,
                total_stages=total,
                completed_stages=completed,
                failed_stages=failed,
                running_stages=running,
                pending_stages=pending,
                progress_percent=progress_percent,
                estimated_seconds_remaining=None,
                recent_stage_completions=recent_completions,
            )

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

    async def retry_stage(
        self,
        workspace_id: UUID,
        project_id: UUID,
        stage_run_id: UUID,
        reason: str,
    ) -> StageRunRead:
        async with self._sessions.begin() as session:
            run = await session.scalar(
                select(StageRun)
                .join(Project, Project.id == StageRun.project_id)
                .where(
                    StageRun.id == stage_run_id,
                    StageRun.project_id == project_id,
                    Project.workspace_id == workspace_id,
                )
                .with_for_update()
            )
            if run is None:
                raise ProjectNotFoundError(stage_run_id)
            if run.status != "EXECUTION_FAILED":
                raise StageNotReadyError(
                    f"stage_run {stage_run_id} has status {run.status!r}; "
                    "only EXECUTION_FAILED stages can be retried"
                )
            run.status = "READY"
            run.state_version += 1
            session.add(
                OutboxEvent(
                    workspace_id=workspace_id,
                    aggregate_type="stage_run",
                    aggregate_id=run.id,
                    event_type="stage_run.retry_requested",
                    payload={
                        "stage_run_id": str(run.id),
                        "project_id": str(project_id),
                        "stage_type": run.stage_type,
                        "reason": reason,
                    },
                )
            )
            await session.flush()
            return _stage_run_read(run)

    async def override_shot_route(
        self,
        workspace_id: UUID,
        project_id: UUID,
        shot_id: UUID,
        route: str,
        reason: str,
        force_rerun: bool,
    ) -> dict:
        _ROUTE_TO_STAGE: dict[str, str] = {
            "B": "VISUAL_SUBTITLE_CLEAN",
            "C": "VISUAL_CHARACTER_REPLACE",
            "D": "VISUAL_BACKGROUND_REPLACE",
            "E": "VISUAL_JOINT_REPLACE",
            "F": "VISUAL_FULL_REGEN",
        }
        async with self._sessions.begin() as session:
            shot = await session.scalar(
                select(Shot)
                .join(Episode, Episode.id == Shot.episode_id)
                .join(Project, Project.id == Episode.project_id)
                .where(
                    Shot.id == shot_id,
                    Episode.project_id == project_id,
                    Project.workspace_id == workspace_id,
                )
                .with_for_update()
            )
            if shot is None:
                raise ProjectNotFoundError(shot_id)
            control = await session.get(ExecutionControl, project_id)
            pending_stage_run_id: UUID | None = None
            if force_rerun and route != "A":
                stage_type = _ROUTE_TO_STAGE[route]
                existing = await session.scalar(
                    select(StageRun)
                    .where(
                        StageRun.project_id == project_id,
                        StageRun.shot_id == shot_id,
                        StageRun.stage_type == stage_type,
                        StageRun.status.in_(("READY", "RUNNING", "PENDING")),
                    )
                    .with_for_update()
                )
                if existing is not None:
                    existing.status = "EXECUTION_FAILED"
                    existing.state_version += 1
                control_version = control.control_version if control is not None else 1
                new_run = StageRun(
                    id=self._id_factory(),
                    project_id=project_id,
                    episode_id=shot.episode_id,
                    shot_id=shot_id,
                    stage_type=stage_type,
                    status="READY",
                    idempotency_key=f"override:{shot_id}:{route}:{self._id_factory()}",
                    runtime_profile_id="gpu-visual",
                    observed_control_version=control_version,
                    params={"shot_id": str(shot_id), "route": route, "override_reason": reason},
                )
                session.add(new_run)
                await session.flush()
                pending_stage_run_id = new_run.id
            session.add(
                OutboxEvent(
                    workspace_id=workspace_id,
                    aggregate_type="shot",
                    aggregate_id=shot_id,
                    event_type="stage_run.route_override_requested",
                    payload={
                        "shot_id": str(shot_id),
                        "project_id": str(project_id),
                        "route": route,
                        "reason": reason,
                        "force_rerun": force_rerun,
                        "pending_stage_run_id": (
                            str(pending_stage_run_id) if pending_stage_run_id else None
                        ),
                    },
                )
            )
            await session.flush()
            return {
                "shot_id": shot_id,
                "route": route,
                "pending_stage_run_id": pending_stage_run_id,
            }

    async def list_failed_stages(
        self,
        workspace_id: UUID,
        project_id: UUID,
        stage_type: str | None = None,
        episode_id: UUID | None = None,
        status: str = "EXECUTION_FAILED",
    ) -> list[FailedStageRead]:
        async with self._sessions() as session:
            exists = await session.scalar(
                select(Project.id).where(
                    Project.id == project_id,
                    Project.workspace_id == workspace_id,
                )
            )
            if exists is None:
                raise ProjectNotFoundError(project_id)
            attempt_ranked = (
                select(
                    StageAttempt.stage_run_id,
                    StageAttempt.error_class,
                    StageAttempt.error_detail,
                    func.row_number()
                    .over(
                        partition_by=StageAttempt.stage_run_id,
                        order_by=StageAttempt.attempt_no.desc(),
                    )
                    .label("rn"),
                )
                .subquery("attempt_ranked")
            )
            latest_attempt = (
                select(attempt_ranked).where(attempt_ranked.c.rn == 1).subquery("latest_attempt")
            )
            counts_subq = (
                select(
                    StageAttempt.stage_run_id,
                    func.count().label("attempt_count"),
                    func.max(StageAttempt.started_at).label("last_attempt_at"),
                )
                .group_by(StageAttempt.stage_run_id)
                .subquery("attempt_counts")
            )
            query = (
                select(
                    StageRun,
                    latest_attempt.c.error_class,
                    latest_attempt.c.error_detail,
                    counts_subq.c.attempt_count,
                    counts_subq.c.last_attempt_at,
                )
                .outerjoin(latest_attempt, latest_attempt.c.stage_run_id == StageRun.id)
                .outerjoin(counts_subq, counts_subq.c.stage_run_id == StageRun.id)
                .where(
                    StageRun.project_id == project_id,
                    StageRun.status == status,
                )
            )
            if stage_type is not None:
                query = query.where(StageRun.stage_type == stage_type)
            if episode_id is not None:
                query = query.where(StageRun.episode_id == episode_id)
            rows = list(
                await session.execute(query.order_by(StageRun.created_at.desc()))
            )
            return [
                FailedStageRead(
                    stage_run_id=row.StageRun.id,
                    stage_type=row.StageRun.stage_type,
                    episode_id=row.StageRun.episode_id,
                    shot_id=row.StageRun.shot_id,
                    status=row.StageRun.status,
                    error_class=row.error_class,
                    error_detail=row.error_detail,
                    attempt_count=row.attempt_count or 0,
                    last_attempt_at=row.last_attempt_at,
                    created_at=row.StageRun.created_at,
                )
                for row in rows
            ]


    async def create_evaluator_release(
        self, workspace_id: UUID, payload: EvaluatorReleaseCreate
    ) -> EvaluatorReleaseRead:
        async with self._sessions.begin() as session:
            await session.execute(
                insert(Workspace)
                .values(id=workspace_id, name=f"Workspace {workspace_id}")
                .on_conflict_do_nothing(index_elements=[Workspace.id])
            )
            next_version = int(
                await session.scalar(
                    select(func.coalesce(func.max(EvaluatorRelease.version), 0) + 1).where(
                        EvaluatorRelease.workspace_id == workspace_id,
                        EvaluatorRelease.evaluator_key == payload.evaluator_key,
                    )
                )
            )
            release = EvaluatorRelease(
                id=self._id_factory(),
                workspace_id=workspace_id,
                evaluator_key=payload.evaluator_key,
                release_name=payload.release_name,
                version=next_version,
                status="ACTIVE",
                metric_definitions=[m.model_dump(mode="json") for m in payload.metric_definitions],
                thresholds=dict(payload.thresholds),
                state_version=1,
            )
            session.add(release)
            session.add(
                OutboxEvent(
                    workspace_id=workspace_id,
                    aggregate_type="evaluator_release",
                    aggregate_id=release.id,
                    event_type="evaluator_release.created",
                    payload={
                        "evaluator_release_id": str(release.id),
                        "evaluator_key": release.evaluator_key,
                        "version": release.version,
                    },
                )
            )
            try:
                await session.flush()
            except IntegrityError as exc:
                raise EvaluatorConflictError("evaluator release already exists") from exc
            return _evaluator_release_read(release)

    async def list_evaluator_releases(
        self, workspace_id: UUID, evaluator_key: str | None = None
    ) -> list[EvaluatorReleaseRead]:
        async with self._sessions() as session:
            query = select(EvaluatorRelease).where(
                EvaluatorRelease.workspace_id == workspace_id
            )
            if evaluator_key is not None:
                query = query.where(EvaluatorRelease.evaluator_key == evaluator_key)
            rows = list(
                await session.scalars(
                    query.order_by(EvaluatorRelease.evaluator_key, EvaluatorRelease.version.desc())
                )
            )
            return [_evaluator_release_read(row) for row in rows]

    async def get_evaluator_release(
        self, workspace_id: UUID, evaluator_release_id: UUID
    ) -> EvaluatorReleaseRead:
        async with self._sessions() as session:
            release = await session.scalar(
                select(EvaluatorRelease).where(
                    EvaluatorRelease.id == evaluator_release_id,
                    EvaluatorRelease.workspace_id == workspace_id,
                )
            )
            if release is None:
                raise ProjectNotFoundError(evaluator_release_id)
            return _evaluator_release_read(release)

    async def get_active_evaluator(
        self, workspace_id: UUID, evaluator_key: str
    ) -> EvaluatorReleaseRead:
        async with self._sessions() as session:
            release = await session.scalar(
                select(EvaluatorRelease)
                .where(
                    EvaluatorRelease.workspace_id == workspace_id,
                    EvaluatorRelease.evaluator_key == evaluator_key,
                    EvaluatorRelease.status == "ACTIVE",
                )
                .order_by(EvaluatorRelease.version.desc())
                .limit(1)
            )
            if release is None:
                raise ProjectNotFoundError(evaluator_key)
            return _evaluator_release_read(release)

    async def deprecate_evaluator_release(
        self, workspace_id: UUID, evaluator_release_id: UUID
    ) -> EvaluatorReleaseRead:
        async with self._sessions.begin() as session:
            release = await session.scalar(
                select(EvaluatorRelease)
                .where(
                    EvaluatorRelease.id == evaluator_release_id,
                    EvaluatorRelease.workspace_id == workspace_id,
                )
                .with_for_update()
            )
            if release is None:
                raise ProjectNotFoundError(evaluator_release_id)
            if release.status == "DEPRECATED":
                raise EvaluatorConflictError("evaluator release is already deprecated")
            release.status = "DEPRECATED"
            release.state_version += 1
            session.add(
                OutboxEvent(
                    workspace_id=workspace_id,
                    aggregate_type="evaluator_release",
                    aggregate_id=release.id,
                    event_type="evaluator_release.deprecated",
                    payload={
                        "evaluator_release_id": str(release.id),
                        "evaluator_key": release.evaluator_key,
                    },
                )
            )
            await session.flush()
            return _evaluator_release_read(release)

    async def submit_qc_evidence(
        self, workspace_id: UUID, project_id: UUID, payload: QcEvidenceCreate
    ) -> None:
        async with self._sessions.begin() as session:
            variant = await session.scalar(
                select(RenderVariant)
                .join(CandidateGroup, CandidateGroup.id == RenderVariant.candidate_group_id)
                .join(Project, Project.id == CandidateGroup.project_id)
                .where(
                    RenderVariant.id == payload.render_variant_id,
                    Project.id == project_id,
                    Project.workspace_id == workspace_id,
                )
                .with_for_update()
            )
            if variant is None:
                raise ProjectNotFoundError(payload.render_variant_id)
            evaluator = await session.scalar(
                select(EvaluatorRelease).where(
                    EvaluatorRelease.id == payload.evaluator_release_id,
                    EvaluatorRelease.workspace_id == workspace_id,
                )
            )
            if evaluator is None:
                raise ProjectNotFoundError(payload.evaluator_release_id)
            for result in payload.results:
                stmt = (
                    insert(QcResult)
                    .values(
                        id=self._id_factory(),
                        render_variant_id=payload.render_variant_id,
                        metric_name=result["metric_name"],
                        metric_version=result["metric_version"],
                        evaluator_release=result["evaluator_release"],
                        score=float(result["score"]),
                        verdict=result["verdict"],
                        hard_failure=bool(result.get("hard_failure", False)),
                        details=result.get("details", {}),
                    )
                    .on_conflict_do_update(
                        index_elements=[
                            "render_variant_id",
                            "metric_name",
                            "metric_version",
                            "evaluator_release",
                        ],
                        set_={
                            "score": result["score"],
                            "verdict": result["verdict"],
                            "hard_failure": result.get("hard_failure", False),
                            "details": result.get("details", {}),
                        },
                    )
                )
                await session.execute(stmt)
            metric_defs = {
                m["metric_name"]: m for m in evaluator.metric_definitions
            }
            thresholds: dict[str, float] = dict(evaluator.thresholds)
            hard_fail = False
            for result in payload.results:
                mname = result["metric_name"]
                score = float(result["score"])
                mdef = metric_defs.get(mname, {})
                hfb = mdef.get("hard_failure_below")
                if hfb is not None and score < hfb:
                    hard_fail = True
                    break
            if hard_fail:
                new_status = "QC_FAILED"
                event_type = "qc.hard_failure"
            else:
                all_pass = all(
                    any(
                        r["metric_name"] == mname and float(r["score"]) >= threshold
                        for r in payload.results
                    )
                    for mname, threshold in thresholds.items()
                )
                if thresholds and all_pass:
                    new_status = "QC_PASSED"
                    event_type = "qc.passed"
                else:
                    new_status = "REVIEW"
                    event_type = "qc.review"
            variant.status = new_status
            session.add(
                OutboxEvent(
                    workspace_id=workspace_id,
                    aggregate_type="render_variant",
                    aggregate_id=variant.id,
                    event_type=event_type,
                    payload={
                        "render_variant_id": str(variant.id),
                        "evaluator_release_id": str(payload.evaluator_release_id),
                        "status": new_status,
                    },
                )
            )
            await session.flush()

    async def get_project_qc_stats(
        self, workspace_id: UUID, project_id: UUID
    ) -> dict:
        async with self._sessions() as session:
            exists = await session.scalar(
                select(Project.id).where(
                    Project.id == project_id, Project.workspace_id == workspace_id
                )
            )
            if exists is None:
                raise ProjectNotFoundError(project_id)
            _VISUAL_ROUTE_STAGES = frozenset({
                "VISUAL_CHARACTER_REPLACE",
                "VISUAL_BACKGROUND_REPLACE",
                "VISUAL_JOINT_REPLACE",
                "VISUAL_FULL_REGEN",
                "VISUAL_SUBTITLE_CLEAN",
            })
            # Total VISUAL_QC stages
            total_visual_stages = await session.scalar(
                select(func.count(StageRun.id)).where(
                    StageRun.project_id == project_id,
                    StageRun.stage_type == "VISUAL_QC",
                )
            ) or 0
            # Completed VISUAL_QC stages (OUTPUT_READY or COMPLETED)
            completed_stages = list(
                await session.scalars(
                    select(StageRun).where(
                        StageRun.project_id == project_id,
                        StageRun.stage_type == "VISUAL_QC",
                        StageRun.status.in_(["COMPLETED", "OUTPUT_READY"]),
                    )
                )
            )
            completed_run_ids = [r.id for r in completed_stages]
            # Load domain artifacts for VISUAL_QC_REPORT to determine pass/fail/review
            qc_docs = list(
                await session.scalars(
                    select(AnalysisDocument).where(
                        AnalysisDocument.project_id == project_id,
                        AnalysisDocument.source_stage_run_id.in_(completed_run_ids),
                        AnalysisDocument.document_type == "VISUAL_QC_REPORT",
                    )
                )
            )
            qc_passed = 0
            qc_failed = 0
            qc_review = 0
            for doc in qc_docs:
                payload = doc.payload or {}
                if payload.get("has_hard_failure"):
                    qc_failed += 1
                else:
                    verdicts = payload.get("verdicts", {})
                    if any(v == "FAIL" for v in verdicts.values()):
                        qc_review += 1
                    else:
                        qc_passed += 1
            # Also count EXECUTION_FAILED VISUAL_QC stages as failed
            exec_failed = await session.scalar(
                select(func.count(StageRun.id)).where(
                    StageRun.project_id == project_id,
                    StageRun.stage_type == "VISUAL_QC",
                    StageRun.status == "EXECUTION_FAILED",
                )
            ) or 0
            qc_failed += exec_failed
            pending = await session.scalar(
                select(func.count(StageRun.id)).where(
                    StageRun.project_id == project_id,
                    StageRun.stage_type == "VISUAL_QC",
                    StageRun.status.in_(["READY", "PENDING", "RUNNING"]),
                )
            ) or 0
            denominator = qc_passed + qc_failed
            failure_rate = qc_failed / denominator if denominator > 0 else 0.0
            # Circuit breaker: check visual route stages
            total_route = await session.scalar(
                select(func.count(StageRun.id)).where(
                    StageRun.project_id == project_id,
                    StageRun.stage_type.in_(_VISUAL_ROUTE_STAGES),
                    StageRun.status.in_(["COMPLETED", "EXECUTION_FAILED"]),
                )
            ) or 0
            circuit_breaker_active = False
            if total_route >= 10:
                failed_route = await session.scalar(
                    select(func.count(StageRun.id)).where(
                        StageRun.project_id == project_id,
                        StageRun.stage_type.in_(_VISUAL_ROUTE_STAGES),
                        StageRun.status == "EXECUTION_FAILED",
                    )
                ) or 0
                circuit_breaker_active = failed_route / total_route > 0.5
            return {
                "total_visual_stages": total_visual_stages,
                "qc_passed": qc_passed,
                "qc_failed": qc_failed,
                "qc_review": qc_review,
                "pending": pending,
                "failure_rate": failure_rate,
                "circuit_breaker_active": circuit_breaker_active,
            }

    async def get_project_cost_report(
        self, workspace_id: UUID, project_id: UUID
    ) -> ProjectCostReport:
        """Aggregate cost data from stage_attempts for the project."""
        async with self._sessions() as session:
            exists = await session.scalar(
                select(Project).where(
                    Project.id == project_id,
                    Project.workspace_id == workspace_id,
                )
            )
            if exists is None:
                raise ProjectNotFoundError(project_id)
            project = exists
            now = datetime.now(UTC)

            # 1. Total cost across all stage_attempts for the project
            total_cost_row = await session.scalar(
                select(func.coalesce(func.sum(StageAttempt.cost_usd), Decimal("0")))
                .join(StageRun, StageRun.id == StageAttempt.stage_run_id)
                .where(StageRun.project_id == project_id)
            )
            total_cost = Decimal(str(total_cost_row or "0"))

            # 2. By-stage breakdown
            stage_rows = list(
                await session.execute(
                    select(
                        StageRun.stage_type,
                        func.count(StageRun.id.distinct()).label("stage_run_count"),
                        func.coalesce(func.sum(StageAttempt.cost_usd), 0).label("total_cost"),
                        func.coalesce(func.avg(StageAttempt.cost_usd), 0).label("avg_cost"),
                    )
                    .join(StageAttempt, StageAttempt.stage_run_id == StageRun.id)
                    .where(StageRun.project_id == project_id)
                    .group_by(StageRun.stage_type)
                    .order_by(StageRun.stage_type)
                )
            )

            # Compute p95 latency per stage_type by fetching durations
            stage_durations: dict[str, list[float]] = {}
            duration_rows = list(
                await session.execute(
                    select(
                        StageRun.stage_type,
                        StageAttempt.started_at,
                        StageAttempt.finished_at,
                    )
                    .join(StageAttempt, StageAttempt.stage_run_id == StageRun.id)
                    .where(
                        StageRun.project_id == project_id,
                        StageAttempt.finished_at.is_not(None),
                    )
                )
            )
            for stage_type, started_at, finished_at in duration_rows:
                if started_at is not None and finished_at is not None:
                    dur = (finished_at - started_at).total_seconds()
                    stage_durations.setdefault(stage_type, []).append(max(0.0, dur))

            def _p95(values: list[float]) -> float:
                if not values:
                    return 0.0
                sorted_vals = sorted(values)
                idx = int(len(sorted_vals) * 0.95)
                return sorted_vals[min(idx, len(sorted_vals) - 1)]

            by_stage = [
                StageCostEntry(
                    stage_type=row.stage_type,
                    stage_run_count=int(row.stage_run_count),
                    total_cost_usd=Decimal(str(row.total_cost)).quantize(Decimal("0.000001")),
                    avg_cost_usd=Decimal(str(row.avg_cost)).quantize(Decimal("0.000001")),
                    p95_latency_seconds=_p95(stage_durations.get(row.stage_type, [])),
                )
                for row in stage_rows
            ]

            # 3. By-model breakdown
            model_rows = list(
                await session.execute(
                    select(
                        ModelRelease.model_key,
                        ModelRelease.release_name,
                        func.count(StageAttempt.id).label("invocation_count"),
                        func.coalesce(func.sum(StageAttempt.cost_usd), 0).label("total_cost"),
                    )
                    .join(StageRun, StageRun.id == StageAttempt.stage_run_id)
                    .join(ModelRelease, ModelRelease.id == StageRun.model_release_id)
                    .where(StageRun.project_id == project_id)
                    .group_by(ModelRelease.model_key, ModelRelease.release_name)
                    .order_by(ModelRelease.model_key)
                )
            )
            by_model = [
                ModelCostEntry(
                    model_key=row.model_key,
                    model_release_name=row.release_name,
                    invocation_count=int(row.invocation_count),
                    total_cost_usd=Decimal(str(row.total_cost)).quantize(Decimal("0.000001")),
                    total_gpu_seconds=0.0,
                )
                for row in model_rows
            ]

            # 4. Episode and shot counts
            episode_count = int(
                await session.scalar(
                    select(func.count(Episode.id)).where(Episode.project_id == project_id)
                ) or 0
            )
            shot_count = int(
                await session.scalar(
                    select(func.count(Shot.id))
                    .join(Episode, Episode.id == Shot.episode_id)
                    .where(Episode.project_id == project_id)
                ) or 0
            )

            zero = Decimal("0.000000")
            cost_per_episode = (
                (total_cost / episode_count).quantize(Decimal("0.000001"))
                if episode_count > 0
                else zero
            )
            cost_per_shot = (
                (total_cost / shot_count).quantize(Decimal("0.000001"))
                if shot_count > 0
                else zero
            )

            budget_usd: Decimal | None = project.budget_hard_limit
            budget_utilization_pct: float | None = None
            if budget_usd is not None and budget_usd > 0:
                budget_utilization_pct = float(total_cost / budget_usd * 100)

            return ProjectCostReport(
                project_id=project_id,
                workspace_id=workspace_id,
                report_generated_at=now,
                total_cost_usd=total_cost.quantize(Decimal("0.000001")),
                by_stage=by_stage,
                by_model=by_model,
                episode_count=episode_count,
                shot_count=shot_count,
                cost_per_episode_usd=cost_per_episode,
                cost_per_shot_usd=cost_per_shot,
                budget_usd=(
                    Decimal(str(budget_usd)).quantize(Decimal("0.000001"))
                    if budget_usd is not None
                    else None
                ),
                budget_utilization_pct=budget_utilization_pct,
            )

    async def list_expired_assets(
        self,
        workspace_id: UUID,
        project_id: UUID,
        policy: object,
    ) -> list[dict]:
        """List orphan assets eligible for deletion based on retention policy.

        Returns a list of dicts with keys:
          asset_id, object_uri, reason, age_days, delete_after
        """
        async with self._sessions() as session:
            exists = await session.scalar(
                select(Project.id).where(
                    Project.id == project_id,
                    Project.workspace_id == workspace_id,
                )
            )
            if exists is None:
                raise ProjectNotFoundError(project_id)
            now = datetime.now(UTC)
            rows = await session.scalars(
                select(OrphanAsset).where(
                    OrphanAsset.project_id == project_id,
                    OrphanAsset.delete_after <= now,
                )
            )
            result: list[dict] = []
            for asset in rows:
                age_days = max(0, (now - asset.created_at.replace(tzinfo=UTC)).days)
                result.append(
                    {
                        "asset_id": asset.id,
                        "object_uri": asset.object_uri,
                        "reason": asset.reason,
                        "age_days": age_days,
                        "delete_after": asset.delete_after,
                    }
                )
            return result

    async def cleanup_expired_orphans(
        self,
        workspace_id: UUID,
        project_id: UUID | None = None,
    ) -> int:
        """Delete orphan_assets past their delete_after date. Returns count deleted."""
        async with self._sessions.begin() as session:
            now = datetime.now(UTC)
            where_clauses = [OrphanAsset.delete_after <= now]
            if project_id is not None:
                exists = await session.scalar(
                    select(Project.id).where(
                        Project.id == project_id,
                        Project.workspace_id == workspace_id,
                    )
                )
                if exists is None:
                    raise ProjectNotFoundError(project_id)
                where_clauses.append(OrphanAsset.project_id == project_id)
            else:
                # Restrict to workspace projects
                project_ids_sq = select(Project.id).where(
                    Project.workspace_id == workspace_id
                )
                where_clauses.append(OrphanAsset.project_id.in_(project_ids_sq))

            rows = await session.scalars(
                select(OrphanAsset).where(*where_clauses)
            )
            assets = list(rows)
            for asset in assets:
                await session.delete(asset)
            return len(assets)


def _stage_run_read(run: StageRun) -> StageRunRead:
    return StageRunRead(
        id=run.id,
        project_id=run.project_id,
        job_id=run.job_id,
        episode_id=run.episode_id,
        shot_id=run.shot_id,
        stage_type=run.stage_type,
        status=run.status,
        state_version=run.state_version,
        created_at=run.created_at or datetime.now(UTC),
        updated_at=run.updated_at or datetime.now(UTC),
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


def _media_asset_record(asset: MediaAsset) -> dict:
    return {
        "id": asset.id,
        "object_uri": asset.object_uri,
        "sha256": asset.sha256,
        "size_bytes": asset.size_bytes,
        "content_type": asset.content_type,
        "metadata": asset.metadata_json,
    }


def _delivery_read(delivery: Delivery) -> DeliveryRead:
    return DeliveryRead(
        id=delivery.id,
        workspace_id=delivery.workspace_id,
        project_id=delivery.project_id,
        episode_id=delivery.episode_id,
        version=delivery.version,
        status=delivery.status,
        state_version=delivery.state_version,
        c2pa_status=delivery.c2pa_status,
        manifest_fingerprint=delivery.manifest_fingerprint,
        manifest=(
            DeliveryManifestBuilder.build(**delivery.manifest)
            if delivery.manifest is not None
            else None
        ),
        approved_by=delivery.approved_by,
        approved_at=delivery.approved_at,
        created_at=delivery.created_at,
        updated_at=delivery.updated_at,
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


def _evaluator_release_read(release: EvaluatorRelease) -> EvaluatorReleaseRead:
    return EvaluatorReleaseRead(
        id=release.id,
        workspace_id=release.workspace_id,
        evaluator_key=release.evaluator_key,
        release_name=release.release_name,
        version=release.version,
        status=release.status,
        metric_definitions=list(release.metric_definitions),
        thresholds=dict(release.thresholds),
        state_version=release.state_version,
        created_at=release.created_at,
        updated_at=release.updated_at,
    )
