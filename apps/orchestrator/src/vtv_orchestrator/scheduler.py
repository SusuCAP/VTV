from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from vtv_db.models import (
    AnalysisDocument,
    ArtifactRelease,
    ArtifactReleaseDependency,
    Job,
    MediaAsset,
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
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

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
            params=claim.params,
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
    if claim.stage_type != "TTS_GENERATE":
        return None
    try:
        request = claim.params["tts_request"]
        snapshot = request["voice_release"]["rights"]
        localized = request["localized"]
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
    if "voice_clone" not in release.allowed_operations:
        return "OPERATION_NOT_ALLOWED"
    if localized.get("target_market") not in release.allowed_markets:
        return "MARKET_NOT_ALLOWED"
    if localized.get("target_language") not in release.allowed_languages:
        return "LANGUAGE_NOT_ALLOWED"
    if request.get("commercial_use", True) and release.commercial_scope != "COMMERCIAL":
        return "COMMERCIAL_USE_NOT_ALLOWED"
    return None


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
