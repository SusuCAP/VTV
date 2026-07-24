import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from hashlib import sha256
from uuid import UUID, uuid4

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from vtv_db.models import (
    AnalysisDocument,
    ArtifactRelease,
    ArtifactReleaseDependency,
    BenchmarkRelease,
    Delivery,
    DeliveryAsset,
    Job,
    MediaAsset,
    ModelRelease,
    OrphanAsset,
    OutboxEvent,
    Project,
    RenderVariant,
    RightsRelease,
    StageAttempt,
    StageDependency,
    StageRun,
)
from vtv_db.queries import CLAIM_READY_STAGE, COMMIT_OUTPUT_READY, PROMOTE_READY_DEPENDENTS
from vtv_schemas.jobs import AssetRef, StageJob, StageResult

from .config import Settings, get_settings, model_runtime_for_stage


@dataclass(frozen=True, slots=True)
class ClaimedStage:
    stage_run_id: UUID
    stage_attempt_id: UUID
    lease_token: UUID
    state_version: int
    observed_control_version: int
    stage_type: str
    project_id: UUID
    workspace_id: UUID
    episode_id: UUID | None
    shot_id: UUID | None
    candidate_group_id: UUID | None
    job_id: UUID | None
    idempotency_key: str
    runtime_profile_id: str
    model_release_id: UUID | None
    params: dict


class Scheduler:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        settings: Settings | None = None,
    ) -> None:
        self._sessions = sessions
        self._settings = settings or get_settings()

    async def claim_one(self, worker_id: str, lease_seconds: int = 300) -> ClaimedStage | None:
        async with self._sessions.begin() as session:
            row = (
                await session.execute(
                    CLAIM_READY_STAGE,
                    {"lease_owner": worker_id, "lease_seconds": lease_seconds},
                )
            ).mappings().first()
            if row is None:
                return None
            attempt_no = (
                await session.scalar(
                    select(func.coalesce(func.max(StageAttempt.attempt_no), 0) + 1).where(
                        StageAttempt.stage_run_id == row["id"]
                    )
                )
            )
            attempt = StageAttempt(
                id=uuid4(),
                stage_run_id=row["id"],
                attempt_no=attempt_no,
                worker_id=worker_id,
                status="RUNNING",
            )
            session.add(attempt)
            workspace_id = await session.scalar(
                select(Project.workspace_id).where(Project.id == row["project_id"])
            )
            if workspace_id is None:
                raise ValueError("claimed stage project not found")
            if row["job_id"]:
                await session.execute(
                    update(Job)
                    .where(Job.id == row["job_id"], Job.status == "QUEUED")
                    .values(status="RUNNING")
                )
            await session.flush()
            return ClaimedStage(
                stage_run_id=row["id"],
                stage_attempt_id=attempt.id,
                lease_token=attempt.lease_token,
                state_version=row["state_version"],
                observed_control_version=row["observed_control_version"],
                stage_type=row["stage_type"],
                project_id=row["project_id"],
                workspace_id=workspace_id,
                episode_id=row["episode_id"],
                shot_id=row["shot_id"],
                candidate_group_id=row["candidate_group_id"],
                job_id=row["job_id"],
                idempotency_key=row["idempotency_key"],
                runtime_profile_id=row["runtime_profile_id"],
                model_release_id=row["model_release_id"],
                params=row["params"],
            )

    async def build_job(self, claim: ClaimedStage) -> StageJob:
        async with self._sessions() as session:
            dependency_ids = select(StageDependency.depends_on_stage_run_id).where(
                StageDependency.stage_run_id == claim.stage_run_id
            )
            assets = list(
                await session.scalars(
                    select(MediaAsset).where(MediaAsset.source_stage_run_id.in_(dependency_ids))
                )
            )
            source_asset_id = claim.params.get("source_asset_id")
            if source_asset_id and claim.stage_type == "INGEST_VALIDATE":
                source = await session.get(MediaAsset, UUID(source_asset_id))
                if source is not None:
                    assets.append(source)
            explicit_asset_ids = claim.params.get("input_asset_ids", [])
            if explicit_asset_ids:
                identifiers = [UUID(value) for value in explicit_asset_ids]
                explicit_assets = list(
                    await session.scalars(
                        select(MediaAsset).where(
                            MediaAsset.id.in_(identifiers),
                            MediaAsset.workspace_id == claim.workspace_id,
                            MediaAsset.project_id == claim.project_id,
                        )
                    )
                )
                if {item.id for item in explicit_assets} != set(identifiers):
                    raise ValueError("one or more explicit stage input assets are missing")
                assets.extend(explicit_assets)
            params = claim.params
            # Inject model_runtime adapter modes from orchestrator settings when not
            # already present in the stored stage params (allows per-stage override).
            runtime_override = model_runtime_for_stage(claim.stage_type, self._settings)
            if runtime_override and "model_runtime" not in params:
                params = {**params, "model_runtime": runtime_override}
            elif runtime_override and isinstance(params.get("model_runtime"), dict):
                # Merge: stored params take precedence; fill in any missing keys
                params = {
                    **params,
                    "model_runtime": {**runtime_override, **params["model_runtime"]},
                }
            if claim.stage_type == "ASSEMBLE_EPISODE":
                template = claim.params.get("episode_assembly_template")
                if not isinstance(template, dict):
                    raise ValueError("ASSEMBLE_EPISODE is missing its immutable template")
                assets, request = _resolve_assembly_inputs(assets, template)
                params = {
                    **claim.params,
                    "episode_assembly_request": request,
                }
            elif claim.stage_type == "DELIVERY_EVIDENCE":
                template = claim.params.get("delivery_evidence_template")
                if not isinstance(template, dict):
                    raise ValueError("DELIVERY_EVIDENCE is missing its immutable template")
                assets, request = await _resolve_delivery_evidence(
                    session, claim, assets, template
                )
                params = {
                    **claim.params,
                    "delivery_evidence_request": request,
                }
            elif claim.stage_type == "SHOT_ROUTING":
                params = await _resolve_shot_routing_params(session, claim)
            elif claim.stage_type == "C2PA_SIGN":
                params = await _resolve_c2pa_sign_params(session, claim)
        return StageJob(
            stage_run_id=claim.stage_run_id,
            stage_attempt_id=claim.stage_attempt_id,
            project_id=claim.project_id,
            episode_id=claim.episode_id,
            shot_id=claim.shot_id,
            candidate_group_id=claim.candidate_group_id,
            idempotency_key=claim.idempotency_key,
            stage_type=claim.stage_type,
            input_assets=[
                AssetRef(
                    uri=asset.object_uri,
                    sha256=asset.sha256,
                    media_type=asset.content_type,
                    size_bytes=asset.size_bytes,
                    metadata=asset.metadata_json,
                )
                for asset in assets
            ],
            output_prefix=(
                f"memory://workspaces/{claim.workspace_id}/projects/{claim.project_id}"
                f"/jobs/{claim.job_id}/stages/{claim.stage_run_id}"
            ),
            runtime_profile_id=claim.runtime_profile_id,
            model_release_id=claim.model_release_id,
            observed_control_version=claim.observed_control_version,
            params=params,
            trace_id=f"stage-{claim.stage_run_id}",
        )

    async def commit_result(self, claim: ClaimedStage, result: StageResult) -> bool:
        if result.stage_run_id != claim.stage_run_id:
            raise ValueError("result stage_run_id does not match claim")
        if result.stage_attempt_id != claim.stage_attempt_id:
            raise ValueError("result stage_attempt_id does not match claim")
        if result.status == "EXECUTION_FAILED":
            await self._mark_failed(claim, result)
            return False

        async with self._sessions.begin() as session:
            rights_failure = await _rights_commit_failure(session, claim)
            if rights_failure is not None:
                await session.execute(
                    update(StageRun)
                    .where(
                        StageRun.id == claim.stage_run_id,
                        StageRun.status == "RUNNING",
                        StageRun.state_version == claim.state_version,
                    )
                    .values(
                        status="EXECUTION_FAILED",
                        state_version=StageRun.state_version + 1,
                        lease_owner=None,
                        lease_expires_at=None,
                    )
                )
                await session.execute(
                    update(StageAttempt)
                    .where(StageAttempt.id == claim.stage_attempt_id)
                    .values(
                        status="EXECUTION_FAILED",
                        error_class="RIGHTS_BLOCKED",
                        error_detail={"reason": rights_failure, "retryable": False},
                        usage=result.attempt_usage,
                        finished_at=func.now(),
                    )
                )
                _record_orphan_outputs(session, claim, result, "RIGHTS_BLOCKED")
                return False
            committed = (
                await session.execute(
                    COMMIT_OUTPUT_READY,
                    {
                        "stage_run_id": claim.stage_run_id,
                        "stage_attempt_id": claim.stage_attempt_id,
                        "lease_token": claim.lease_token,
                        "expected_state_version": claim.state_version,
                        "observed_control_version": claim.observed_control_version,
                    },
                )
            ).first()
            if committed is None:
                _record_orphan_outputs(
                    session, claim, result, "CONDITIONAL_COMMIT_REJECTED"
                )
                return False
            variant_asset_ids: dict[int, list[UUID]] = {}
            for variant in result.variants:
                for asset in variant.output_assets:
                    asset_id = uuid4()
                    inserted_asset_id = await session.scalar(
                        insert(MediaAsset)
                        .values(
                            id=asset_id,
                            workspace_id=claim.workspace_id,
                            project_id=claim.project_id,
                            source_stage_run_id=claim.stage_run_id,
                            object_uri=asset.uri,
                            sha256=asset.sha256,
                            size_bytes=asset.size_bytes,
                            content_type=asset.media_type,
                            metadata={
                                **asset.metadata,
                                "stage_attempt_id": str(claim.stage_attempt_id),
                                "variant_no": variant.variant_no,
                                "stage_type": claim.stage_type,
                                "episode_id": str(claim.episode_id) if claim.episode_id else None,
                            },
                        )
                        .on_conflict_do_nothing(
                            index_elements=[
                                MediaAsset.workspace_id,
                                MediaAsset.sha256,
                                MediaAsset.object_uri,
                            ]
                        )
                        .returning(MediaAsset.id)
                    )
                    if inserted_asset_id is None:
                        inserted_asset_id = await session.scalar(
                            select(MediaAsset.id).where(
                                MediaAsset.workspace_id == claim.workspace_id,
                                MediaAsset.sha256 == asset.sha256,
                                MediaAsset.object_uri == asset.uri,
                            )
                        )
                    if inserted_asset_id is None:
                        raise RuntimeError("committed output asset could not be resolved")
                    variant_asset_ids.setdefault(variant.variant_no, []).append(
                        inserted_asset_id
                    )
            if claim.candidate_group_id is not None:
                for variant in result.variants:
                    output_ids = variant_asset_ids.get(variant.variant_no, [])
                    if len(output_ids) != 1:
                        raise ValueError(
                            "candidate variant must contain exactly one primary output asset"
                        )
                    session.add(
                        RenderVariant(
                            id=uuid4(),
                            candidate_group_id=claim.candidate_group_id,
                            stage_run_id=claim.stage_run_id,
                            variant_no=variant.variant_no,
                            seed=variant.seed,
                            output_asset_id=output_ids[0],
                            raw_metrics=variant.raw_metrics,
                            allocated_cost=variant.allocated_cost,
                        )
                    )
            if result.domain_artifacts:
                await self._persist_domain_artifacts(session, claim, result)
            await session.execute(
                update(StageAttempt)
                .where(StageAttempt.id == claim.stage_attempt_id)
                .values(status="OUTPUT_READY", usage=result.attempt_usage, finished_at=func.now())
            )
        # After a successful visual stage commit, check the project-level circuit breaker.
        _VISUAL_ROUTE_STAGES = frozenset({
            "VISUAL_CHARACTER_REPLACE",
            "VISUAL_BACKGROUND_REPLACE",
            "VISUAL_JOINT_REPLACE",
            "VISUAL_FULL_REGEN",
            "VISUAL_SUBTITLE_CLEAN",
        })
        if claim.stage_type in _VISUAL_ROUTE_STAGES:
            await self._run_visual_circuit_breaker(claim)
        return True

    async def _persist_domain_artifacts(
        self,
        session: AsyncSession,
        claim: ClaimedStage,
        result: StageResult,
    ) -> None:
        assets = list(
            await session.scalars(
                select(MediaAsset).where(MediaAsset.source_stage_run_id == claim.stage_run_id)
            )
        )
        assets_by_sha = {asset.sha256: asset for asset in assets}
        # Stages that produce no output assets (e.g. VISUAL_QC) need to reference
        # input assets from their dependency stages for the document link.
        if not assets_by_sha:
            dep_run_ids = select(StageDependency.depends_on_stage_run_id).where(
                StageDependency.stage_run_id == claim.stage_run_id
            )
            dep_assets = list(
                await session.scalars(
                    select(MediaAsset).where(
                        MediaAsset.source_stage_run_id.in_(dep_run_ids)
                    )
                )
            )
            assets_by_sha = {asset.sha256: asset for asset in dep_assets}
        release_specs: list[tuple[str, int, MediaAsset, tuple[str, ...]]] = []
        for artifact in result.domain_artifacts:
            asset = assets_by_sha.get(artifact.source_asset_sha256)
            if asset is None:
                raise ValueError(
                    f"domain artifact {artifact.document_type} has no committed output asset"
                )
            await session.execute(
                insert(AnalysisDocument)
                .values(
                    id=uuid4(),
                    project_id=claim.project_id,
                    episode_id=artifact.episode_id or claim.episode_id,
                    source_stage_run_id=claim.stage_run_id,
                    media_asset_id=asset.id,
                    document_type=artifact.document_type,
                    schema_version=artifact.schema_version,
                    payload=artifact.payload,
                )
                .on_conflict_do_nothing(
                    index_elements=[
                        AnalysisDocument.source_stage_run_id,
                        AnalysisDocument.media_asset_id,
                        AnalysisDocument.document_type,
                    ]
                )
            )
            session.add(
                OutboxEvent(
                    workspace_id=claim.workspace_id,
                    aggregate_type="analysis_document",
                    aggregate_id=claim.stage_run_id,
                    event_type="analysis_document.created",
                    payload={
                        "stage_run_id": str(claim.stage_run_id),
                        "document_type": artifact.document_type,
                        "episode_id": str(artifact.episode_id or claim.episode_id)
                        if artifact.episode_id or claim.episode_id
                        else None,
                    },
                )
            )
            if artifact.release_artifact_type:
                release_specs.append(
                    (
                        artifact.release_artifact_type,
                        artifact.release_version or 1,
                        asset,
                        artifact.depends_on_artifact_types,
                    )
                )
        if release_specs:
            await session.scalar(
                select(Project.id)
                .where(Project.id == claim.project_id)
                .with_for_update()
            )
            await self._create_draft_releases(session, claim, release_specs)
        # After DELIVERY_EVIDENCE, schedule C2PA_SIGN if requested
        if (
            claim.stage_type == "DELIVERY_EVIDENCE"
            and any(a.document_type == "QUALITY_REPORT" for a in result.domain_artifacts)
            and claim.params.get("c2pa_requested", False)
        ):
            await self._create_c2pa_sign_stage(session, claim)

    async def _create_c2pa_sign_stage(
        self,
        session: AsyncSession,
        claim: ClaimedStage,
    ) -> None:
        """Create a C2PA_SIGN StageRun as a dependent of the completed DELIVERY_EVIDENCE run."""
        idempotency_key = f"c2pa-sign:{claim.stage_run_id}"
        existing = await session.scalar(
            select(StageRun.id).where(
                StageRun.project_id == claim.project_id,
                StageRun.idempotency_key == idempotency_key,
            )
        )
        if existing is not None:
            return
        c2pa_run = StageRun(
            id=uuid4(),
            project_id=claim.project_id,
            job_id=claim.job_id,
            episode_id=claim.episode_id,
            stage_type="C2PA_SIGN",
            status="PENDING",
            idempotency_key=idempotency_key,
            runtime_profile_id="local",
            state_version=1,
            observed_control_version=claim.observed_control_version,
            priority=0,
            params={
                "assembly_job_id": str(claim.job_id) if claim.job_id else None,
                "episode_id": str(claim.episode_id) if claim.episode_id else None,
                "delivery_evidence_stage_run_id": str(claim.stage_run_id),
            },
        )
        session.add(c2pa_run)
        await session.flush()
        session.add(
            StageDependency(
                stage_run_id=c2pa_run.id,
                depends_on_stage_run_id=claim.stage_run_id,
            )
        )
        if claim.job_id:
            await session.execute(
                update(Job)
                .where(Job.id == claim.job_id)
                .values(total_stages=Job.total_stages + 1)
            )

    async def _create_draft_releases(
        self,
        session: AsyncSession,
        claim: ClaimedStage,
        specs: list[tuple[str, int, MediaAsset, tuple[str, ...]]],
    ) -> None:
        created: dict[str, ArtifactRelease] = {}
        for artifact_type, expected_version, asset, dependency_types in specs:
            latest = await session.scalar(
                select(ArtifactRelease)
                .where(
                    ArtifactRelease.project_id == claim.project_id,
                    ArtifactRelease.artifact_type == artifact_type,
                )
                .order_by(ArtifactRelease.version.desc())
                .limit(1)
                .with_for_update()
            )
            if latest is not None:
                await _invalidate_release_graph(session, latest.id, claim.project_id)
            actual_version = latest.version + 1 if latest else 1
            if actual_version != expected_version:
                raise ValueError(
                    f"release version changed for {artifact_type}: "
                    f"expected {expected_version}, actual {actual_version}"
                )
            release = ArtifactRelease(
                id=uuid4(),
                project_id=claim.project_id,
                artifact_type=artifact_type,
                version=actual_version,
                status="DRAFT",
                content_asset_id=asset.id,
                supersedes_release_id=latest.id if latest else None,
            )
            session.add(release)
            created[artifact_type] = release
            await session.flush()
            for dependency_type in dependency_types:
                dependency = created.get(dependency_type)
                if dependency is None:
                    raise ValueError(
                        f"release dependency {dependency_type} must precede {artifact_type}"
                    )
                session.add(
                    ArtifactReleaseDependency(
                        upstream_release_id=dependency.id,
                        downstream_release_id=release.id,
                    )
                )
            session.add(
                OutboxEvent(
                    workspace_id=claim.workspace_id,
                    aggregate_type="artifact_release",
                    aggregate_id=release.id,
                    event_type="artifact_release.created",
                    payload={
                        "release_id": str(release.id),
                        "project_id": str(claim.project_id),
                        "artifact_type": artifact_type,
                        "source_stage_run_id": str(claim.stage_run_id),
                    },
                )
            )

    async def _run_visual_circuit_breaker(self, claim: ClaimedStage) -> None:
        """Check project-level visual failure rate and trip the circuit if threshold exceeded."""
        tripped = await self._check_visual_circuit_breaker(claim)
        if not tripped:
            return
        async with self._sessions.begin() as session:
            _VISUAL_ALL_STAGES = frozenset({
                "VISUAL_CHARACTER_REPLACE",
                "VISUAL_BACKGROUND_REPLACE",
                "VISUAL_JOINT_REPLACE",
                "VISUAL_FULL_REGEN",
                "VISUAL_SUBTITLE_CLEAN",
                "VISUAL_KEYFRAME_PREVIEW",
                "VISUAL_QC",
            })
            await session.execute(
                update(StageRun)
                .where(
                    StageRun.project_id == claim.project_id,
                    StageRun.stage_type.in_(_VISUAL_ALL_STAGES),
                    StageRun.status.in_(["READY", "PENDING"]),
                )
                .values(
                    status="EXECUTION_FAILED",
                    state_version=StageRun.state_version + 1,
                    error_detail={"reason": "CIRCUIT_BREAKER", "retryable": False},
                )
            )
            session.add(
                OutboxEvent(
                    workspace_id=claim.workspace_id,
                    aggregate_type="project",
                    aggregate_id=claim.project_id,
                    event_type="visual_production.circuit_breaker_tripped",
                    payload={
                        "project_id": str(claim.project_id),
                        "triggered_by_stage_run_id": str(claim.stage_run_id),
                    },
                )
            )

    async def _check_visual_circuit_breaker(
        self,
        claim: ClaimedStage,
        max_failure_rate: float = 0.5,
    ) -> bool:
        """Return True if visual production should be suspended for this project.

        Checks: if >= 10 visual route stages completed AND failure rate > max_failure_rate,
        return True (circuit open).
        """
        _VISUAL_ROUTE_STAGES = frozenset({
            "VISUAL_CHARACTER_REPLACE",
            "VISUAL_BACKGROUND_REPLACE",
            "VISUAL_JOINT_REPLACE",
            "VISUAL_FULL_REGEN",
            "VISUAL_SUBTITLE_CLEAN",
        })
        async with self._sessions() as session:
            total = await session.scalar(
                select(func.count(StageRun.id)).where(
                    StageRun.project_id == claim.project_id,
                    StageRun.stage_type.in_(_VISUAL_ROUTE_STAGES),
                    StageRun.status.in_(["COMPLETED", "EXECUTION_FAILED"]),
                )
            )
            if (total or 0) < 10:
                return False
            failed = await session.scalar(
                select(func.count(StageRun.id)).where(
                    StageRun.project_id == claim.project_id,
                    StageRun.stage_type.in_(_VISUAL_ROUTE_STAGES),
                    StageRun.status == "EXECUTION_FAILED",
                )
            )
            return (failed or 0) / total > max_failure_rate

    async def finalize_stage(self, claim: ClaimedStage) -> None:
        async with self._sessions.begin() as session:
            run = await session.get(StageRun, claim.stage_run_id, with_for_update=True)
            if run is None or run.status != "OUTPUT_READY":
                raise ValueError("stage is not ready to finalize")
            run.status = "COMPLETED"
            run.state_version += 1
            if claim.job_id:
                job = await session.get(Job, claim.job_id, with_for_update=True)
                if job is None:
                    raise ValueError("parent job not found")
                job.completed_stages += 1
                job.status = "SUCCEEDED" if job.completed_stages == job.total_stages else "RUNNING"
            if claim.job_id:
                await session.execute(PROMOTE_READY_DEPENDENTS, {"job_id": claim.job_id})

    async def _mark_failed(self, claim: ClaimedStage, result: StageResult) -> None:
        async with self._sessions.begin() as session:
            await session.execute(
                update(StageRun)
                .where(StageRun.id == claim.stage_run_id, StageRun.status == "RUNNING")
                .values(status="EXECUTION_FAILED", state_version=StageRun.state_version + 1)
            )
            await session.execute(
                update(StageAttempt)
                .where(StageAttempt.id == claim.stage_attempt_id)
                .values(
                    status="EXECUTION_FAILED",
                    error_class=result.error_class,
                    error_detail=result.error_detail,
                    usage=result.attempt_usage,
                    finished_at=func.now(),
                )
            )


async def _rights_commit_failure(
    session: AsyncSession, claim: ClaimedStage
) -> str | None:
    if claim.stage_type not in {"TTS_GENERATE", "LIPSYNC_GENERATE"}:
        return None
    try:
        if claim.stage_type == "TTS_GENERATE":
            request = claim.params["tts_request"]
            snapshot = request["voice_release"]["rights"]
            market = request["localized"]["target_market"]
            language = request["localized"]["target_language"]
            operation = "voice_clone"
        else:
            request = claim.params["lipsync_request"]
            snapshot = request["rights"]
            market = request["target_market"]
            language = request["target_language"]
            operation = "lipsync"
        rights_id = UUID(snapshot["rights_release_id"])
        expected_version = int(claim.params["rights_state_version"])
        if int(snapshot["state_version"]) != expected_version:
            return "RIGHTS_SNAPSHOT_VERSION_MISMATCH"
    except (KeyError, TypeError, ValueError):
        return "RIGHTS_SNAPSHOT_INVALID"
    release = await session.scalar(
        select(RightsRelease)
        .where(
            RightsRelease.id == rights_id,
            RightsRelease.project_id == claim.project_id,
        )
        .with_for_update()
    )
    if release is None:
        return "RIGHTS_RELEASE_MISSING"
    if release.state_version != expected_version:
        return "RIGHTS_STATE_CHANGED"
    if release.status != "ACTIVE" or release.revoked_at is not None:
        return "RIGHTS_REVOKED"
    now = datetime.now(UTC)
    if now < release.valid_from:
        return "RIGHTS_NOT_YET_VALID"
    if release.expires_at is not None and now >= release.expires_at:
        return "RIGHTS_EXPIRED"
    if operation not in release.allowed_operations:
        return "OPERATION_NOT_ALLOWED"
    if market not in release.allowed_markets:
        return "MARKET_NOT_ALLOWED"
    if language not in release.allowed_languages:
        return "LANGUAGE_NOT_ALLOWED"
    if request.get("commercial_use", True) and release.commercial_scope != "COMMERCIAL":
        return "COMMERCIAL_USE_NOT_ALLOWED"
    return None


async def _resolve_delivery_evidence(
    session: AsyncSession,
    claim: ClaimedStage,
    assets: list[MediaAsset],
    template: dict,
) -> tuple[list[MediaAsset], dict]:
    masters = [
        asset
        for asset in assets
        if asset.metadata_json.get("stage_type") == "ASSEMBLE_EPISODE"
        and asset.content_type.startswith("video/")
    ]
    if len(masters) != 1:
        raise ValueError("DELIVERY_EVIDENCE requires exactly one episode master")
    if claim.job_id is None:
        raise ValueError("DELIVERY_EVIDENCE must belong to an assembly job")
    runs = list(
        await session.scalars(
            select(StageRun)
            .where(
                StageRun.job_id == claim.job_id,
                StageRun.id != claim.stage_run_id,
                StageRun.status == "COMPLETED",
            )
            .order_by(StageRun.created_at, StageRun.id)
        )
    )
    if not runs or not any(run.stage_type == "ASSEMBLE_EPISODE" for run in runs):
        raise ValueError("delivery evidence requires a completed assembly chain")
    run_ids = [run.id for run in runs]
    output_assets = list(
        await session.scalars(
            select(MediaAsset).where(MediaAsset.source_stage_run_id.in_(run_ids))
        )
    )
    outputs_by_run: dict[UUID, list[MediaAsset]] = {}
    for asset in output_assets:
        assert asset.source_stage_run_id is not None
        outputs_by_run.setdefault(asset.source_stage_run_id, []).append(asset)
    dependency_rows = (
        await session.execute(
            select(
                StageDependency.stage_run_id,
                StageDependency.depends_on_stage_run_id,
            ).where(StageDependency.stage_run_id.in_(run_ids))
        )
    ).all()
    dependencies: dict[UUID, set[UUID]] = {}
    for stage_run_id, dependency_id in dependency_rows:
        dependencies.setdefault(stage_run_id, set()).add(dependency_id)
    edit_chain: list[dict] = []
    for run in runs:
        outputs = outputs_by_run.get(run.id, [])
        if not outputs:
            raise ValueError(f"completed stage {run.stage_type} has no committed outputs")
        dependency_assets = [
            asset
            for dependency_id in dependencies.get(run.id, set())
            for asset in outputs_by_run.get(dependency_id, [])
        ]
        if run.stage_type == "ASSEMBLE_EPISODE":
            assembly_template = run.params.get("episode_assembly_template")
            if not isinstance(assembly_template, dict):
                raise ValueError("delivery edit chain has invalid assembly template")
            selected_inputs, _ = _resolve_assembly_inputs(
                dependency_assets, assembly_template
            )
            input_hashes = {asset.sha256 for asset in selected_inputs}
        else:
            input_hashes = {asset.sha256 for asset in dependency_assets}
        explicit_ids = [UUID(value) for value in run.params.get("input_asset_ids", [])]
        if explicit_ids:
            explicit_assets = list(
                await session.scalars(
                    select(MediaAsset).where(
                        MediaAsset.id.in_(explicit_ids),
                        MediaAsset.workspace_id == claim.workspace_id,
                        MediaAsset.project_id == claim.project_id,
                    )
                )
            )
            if {asset.id for asset in explicit_assets} != set(explicit_ids):
                raise ValueError("delivery edit chain has missing explicit inputs")
            input_hashes.update(asset.sha256 for asset in explicit_assets)
        canonical_params = json.dumps(
            run.params,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        edit_chain.append(
            {
                "stage_run_id": str(run.id),
                "stage_type": run.stage_type,
                "input_sha256s": sorted(input_hashes),
                "output_sha256s": sorted(asset.sha256 for asset in outputs),
                "parameters_sha256": sha256(canonical_params.encode()).hexdigest(),
            }
        )
    models: list[dict] = []
    for model_release_id in sorted(
        {run.model_release_id for run in runs if run.model_release_id is not None},
        key=str,
    ):
        release = await session.get(ModelRelease, model_release_id)
        benchmark = (
            await session.get(BenchmarkRelease, release.approved_benchmark_release_id)
            if release is not None and release.approved_benchmark_release_id is not None
            else None
        )
        if release is None or benchmark is None or not benchmark.approved:
            raise ValueError("delivery model provenance requires an approved benchmark")
        seeds = list(
            await session.scalars(
                select(RenderVariant.seed).where(
                    RenderVariant.stage_run_id.in_(
                        [run.id for run in runs if run.model_release_id == model_release_id]
                    ),
                    RenderVariant.seed.is_not(None),
                )
            )
        )
        models.append(
            {
                "model_release_id": str(release.id),
                "model_key": release.model_key,
                "release_name": release.release_name,
                "weights_sha256": benchmark.weights_sha256,
                "seed": seeds[0] if len(set(seeds)) == 1 else None,
            }
        )
    attempts = list(
        await session.scalars(
            select(StageAttempt).where(StageAttempt.stage_run_id.in_(run_ids))
        )
    )
    run_by_id = {run.id: run for run in runs}
    by_stage: dict[str, Decimal] = {}
    provider_usage: list[dict] = []
    for attempt in attempts:
        cost = attempt.cost_usd or Decimal()
        stage_type = run_by_id[attempt.stage_run_id].stage_type
        by_stage[stage_type] = by_stage.get(stage_type, Decimal()) + cost
        if attempt.usage:
            provider_usage.append(
                {
                    "stage_run_id": str(attempt.stage_run_id),
                    "attempt_no": attempt.attempt_no,
                    "usage": attempt.usage,
                    "cost_usd": str(cost),
                }
            )
    master = masters[0]
    request = {
        "source_video_sha256": template["source_video_sha256"],
        "master_video_sha256": master.sha256,
        "project_state_version": template["project_state_version"],
        "duration_ms": template["duration_ms"],
        "edit_chain": edit_chain,
        "models": models,
        "qc": template.get("qc", []),
        "shots": template["shots"],
        "cost": {
            "currency": "USD",
            "total": str(sum(by_stage.values(), Decimal())),
            "by_stage": {key: str(value) for key, value in sorted(by_stage.items())},
            "provider_usage": provider_usage,
        },
        "final_encoding": master.metadata_json,
    }
    return [master], request


def _resolve_assembly_inputs(
    assets: list[MediaAsset], template: dict
) -> tuple[list[MediaAsset], dict]:
    pictures = [
        item
        for item in assets
        if item.metadata_json.get("stage_type") == "PICTURE_CONFORM"
        and item.content_type.startswith("video/")
    ]
    mixes = [
        item
        for item in assets
        if item.metadata_json.get("stage_type") == "AUDIO_MIX"
        and item.content_type.startswith("audio/")
    ]
    subtitles = [
        item
        for item in assets
        if item.metadata_json.get("stage_type") == "SUBTITLE_RENDER"
        and item.content_type == "application/x-subrip"
    ]
    if len(pictures) != 1 or len(mixes) != 1:
        raise ValueError("ASSEMBLE_EPISODE requires one picture master and one audio mix")
    burn_subtitles = template.get("burn_subtitles") is True
    if burn_subtitles and len(subtitles) != 1:
        raise ValueError("burned master requires exactly one SRT dependency")
    selected_assets = [pictures[0], mixes[0]]
    request = {
        **template,
        "source_video_sha256": pictures[0].sha256,
        "mixed_audio_sha256": mixes[0].sha256,
        "subtitle_sha256": subtitles[0].sha256 if burn_subtitles else None,
    }
    if burn_subtitles:
        selected_assets.append(subtitles[0])
    return selected_assets, request


def _record_orphan_outputs(
    session: AsyncSession,
    claim: ClaimedStage,
    result: StageResult,
    reason: str,
) -> None:
    for variant in result.variants:
        for asset in variant.output_assets:
            session.add(
                OrphanAsset(
                    project_id=claim.project_id,
                    stage_attempt_id=claim.stage_attempt_id,
                    object_uri=asset.uri,
                    reason=reason,
                    delete_after=func.now() + func.make_interval(0, 0, 0, 1),
                )
            )


async def _invalidate_release_graph(
    session: AsyncSession, root_release_id: UUID, project_id: UUID
) -> None:
    pending = [root_release_id]
    visited: set[UUID] = set()
    now = datetime.now(UTC)
    while pending:
        current_id = pending.pop()
        if current_id in visited:
            continue
        visited.add(current_id)
        current = await session.get(ArtifactRelease, current_id, with_for_update=True)
        if current is None or current.project_id != project_id:
            raise ValueError("artifact release dependency crosses project boundary")
        if current.status != "STALE":
            current.status = "STALE"
            current.state_version += 1
            current.stale_at = now
        downstream = await session.scalars(
            select(ArtifactReleaseDependency.downstream_release_id).where(
                ArtifactReleaseDependency.upstream_release_id == current_id
            )
        )
        pending.extend(downstream)


async def _resolve_c2pa_sign_params(
    session: AsyncSession,
    claim: ClaimedStage,
) -> dict:
    """Resolve delivery information for a C2PA_SIGN stage at claim time."""
    if claim.episode_id is None:
        raise ValueError("C2PA_SIGN requires an episode_id on the stage run")
    delivery = await session.scalar(
        select(Delivery)
        .where(
            Delivery.project_id == claim.project_id,
            Delivery.episode_id == claim.episode_id,
            Delivery.status == "APPROVED",
        )
        .order_by(Delivery.version.desc())
        .limit(1)
    )
    if delivery is None:
        raise ValueError("C2PA_SIGN: no approved delivery found for episode")
    if delivery.manifest_fingerprint is None:
        raise ValueError("C2PA_SIGN: approved delivery has no manifest fingerprint")
    master_link = await session.scalar(
        select(DeliveryAsset)
        .where(
            DeliveryAsset.delivery_id == delivery.id,
            DeliveryAsset.role == "MASTER_VIDEO",
        )
    )
    if master_link is None:
        raise ValueError("C2PA_SIGN: approved delivery has no MASTER_VIDEO asset")
    master_asset = await session.get(MediaAsset, master_link.asset_id)
    if master_asset is None:
        raise ValueError("C2PA_SIGN: MASTER_VIDEO asset record not found")
    signer_id = claim.params.get("c2pa_signer_id")
    if not isinstance(signer_id, str) or not signer_id.strip():
        raise ValueError(
            "C2PA_SIGN: a configured SDK-backed c2pa_signer_id is required"
        )
    return {
        **claim.params,
        "c2pa_sign_request": {
            "delivery_id": str(delivery.id),
            "manifest_fingerprint": delivery.manifest_fingerprint,
            "master_object_uri": master_asset.object_uri,
            "output_prefix": f"c2pa/{claim.project_id}/{claim.stage_run_id}",
            "signer_id": signer_id,
        },
    }


async def _resolve_shot_routing_params(
    session: AsyncSession,
    claim: ClaimedStage,
) -> dict:
    """Build shot_routing_request from stored AnalysisDocuments at claim time."""
    if claim.episode_id is None:
        raise ValueError("SHOT_ROUTING requires an episode_id on the stage run")

    template = claim.params.get("shot_routing_template") or {}
    shots: list[dict] = template.get("shots") or []

    # Query latest VISION_ANALYSIS for this episode
    vision_doc = await session.scalar(
        select(AnalysisDocument)
        .where(
            AnalysisDocument.project_id == claim.project_id,
            AnalysisDocument.episode_id == claim.episode_id,
            AnalysisDocument.document_type == "VISION_ANALYSIS",
        )
        .order_by(AnalysisDocument.id.desc())
        .limit(1)
    )

    # Query latest AUDIO_ANALYSIS for this episode
    audio_doc = await session.scalar(
        select(AnalysisDocument)
        .where(
            AnalysisDocument.project_id == claim.project_id,
            AnalysisDocument.episode_id == claim.episode_id,
            AnalysisDocument.document_type == "AUDIO_ANALYSIS",
        )
        .order_by(AnalysisDocument.id.desc())
        .limit(1)
    )

    vision_payload: dict = vision_doc.payload if vision_doc is not None else {}
    audio_payload: dict = audio_doc.payload if audio_doc is not None else {}

    return {
        **claim.params,
        "shot_routing_request": {
            "episode_id": str(claim.episode_id),
            "shots": shots,
            "person_observations": vision_payload.get("people") or [],
            "ocr_observations": vision_payload.get("ocr") or [],
            "utterances": audio_payload.get("utterances") or [],
        },
    }
