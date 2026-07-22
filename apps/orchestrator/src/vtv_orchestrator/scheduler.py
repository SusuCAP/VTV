from dataclasses import dataclass
from uuid import UUID, uuid4

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from vtv_db.models import (
    Job,
    MediaAsset,
    OrphanAsset,
    Project,
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
    job_id: UUID | None
    idempotency_key: str
    runtime_profile_id: str
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
                job_id=row["job_id"],
                idempotency_key=row["idempotency_key"],
                runtime_profile_id=row["runtime_profile_id"],
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
                for variant in result.variants:
                    for asset in variant.output_assets:
                        session.add(
                            OrphanAsset(
                                project_id=claim.project_id,
                                stage_attempt_id=claim.stage_attempt_id,
                                object_uri=asset.uri,
                                reason="CONDITIONAL_COMMIT_REJECTED",
                                delete_after=func.now() + func.make_interval(0, 0, 0, 1),
                            )
                        )
                return False
            for variant in result.variants:
                for asset in variant.output_assets:
                    await session.execute(
                        insert(MediaAsset)
                        .values(
                            id=uuid4(),
                            workspace_id=claim.workspace_id,
                            project_id=claim.project_id,
                            source_stage_run_id=claim.stage_run_id,
                            object_uri=asset.uri,
                            sha256=asset.sha256,
                            size_bytes=asset.size_bytes,
                            content_type=asset.media_type,
                            metadata={
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
                    )
            await session.execute(
                update(StageAttempt)
                .where(StageAttempt.id == claim.stage_attempt_id)
                .values(status="OUTPUT_READY", usage=result.attempt_usage, finished_at=func.now())
            )
            return True

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
