from dataclasses import dataclass
from uuid import UUID, uuid4

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from vtv_db.models import Job, OrphanAsset, StageAttempt, StageRun
from vtv_db.queries import CLAIM_READY_STAGE, COMMIT_OUTPUT_READY, PROMOTE_READY_DEPENDENTS
from vtv_schemas.jobs import StageResult


@dataclass(frozen=True, slots=True)
class ClaimedStage:
    stage_run_id: UUID
    stage_attempt_id: UUID
    lease_token: UUID
    state_version: int
    observed_control_version: int
    stage_type: str
    project_id: UUID
    job_id: UUID | None


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
            await session.flush()
            return ClaimedStage(
                stage_run_id=row["id"],
                stage_attempt_id=attempt.id,
                lease_token=attempt.lease_token,
                state_version=row["state_version"],
                observed_control_version=row["observed_control_version"],
                stage_type=row["stage_type"],
                project_id=row["project_id"],
                job_id=row["job_id"],
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
