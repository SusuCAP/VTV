from __future__ import annotations

from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from vtv_db.models import (
    DeletionTombstone,
    ExecutionControl,
    OutboxEvent,
    StageAttempt,
    StageRun,
)
from vtv_db.queries import CLAIM_STAGE_DISPATCH_EVENT
from vtv_schemas.jobs import StageJob, StageResult

from .scheduler import Scheduler


class StageDispatchGateway(Protocol):
    def spawn(self, job: StageJob) -> str: ...

    def get_result(self, modal_call_id: str) -> StageResult | None: ...

    def cancel(self, modal_call_id: str) -> None: ...


@dataclass(frozen=True, slots=True)
class DispatchEventClaim:
    event_id: UUID
    stage_attempt_id: UUID
    publish_attempts: int


@dataclass(frozen=True, slots=True)
class CollectedAttempt:
    stage_attempt_id: UUID
    modal_call_id: str


class OutboxDispatcher:
    """Durable, at-least-once bridge from PostgreSQL to Modal function calls."""

    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        scheduler: Scheduler,
        gateway: StageDispatchGateway,
        *,
        stale_dispatch_seconds: int = 120,
        max_dispatch_attempts: int = 5,
        max_stage_attempts: int = 3,
        attempt_lease_seconds: int = 3600,
    ) -> None:
        self._sessions = sessions
        self._scheduler = scheduler
        self._gateway = gateway
        self._stale_dispatch_seconds = stale_dispatch_seconds
        self._max_dispatch_attempts = max_dispatch_attempts
        self._max_stage_attempts = max_stage_attempts
        self._attempt_lease_seconds = attempt_lease_seconds

    async def dispatch_one(self) -> bool:
        reaped = await self.reap_stale_attempts()
        await self._cancel_tombstoned_dispatches()
        claim = await self._claim_event()
        if claim is None:
            return reaped > 0
        try:
            stage_claim = await self._scheduler.load_claim(claim.stage_attempt_id)
            job = await self._scheduler.build_job(stage_claim)
            modal_call_id = self._gateway.spawn(job)
        except Exception as exc:
            await self._record_dispatch_failure(claim, exc)
            return True

        accepted = await self._record_dispatch_success(claim, modal_call_id)
        if not accepted:
            with suppress(Exception):
                self._gateway.cancel(modal_call_id)
        return True

    async def collect_one(self) -> bool:
        await self.reap_stale_attempts()
        await self._cancel_tombstoned_calls()
        collected = await self._claim_dispatched_attempt()
        if collected is None:
            return False
        try:
            result = self._gateway.get_result(collected.modal_call_id)
        except Exception as exc:
            claim = await self._scheduler.load_claim(collected.stage_attempt_id)
            result = StageResult(
                stage_run_id=claim.stage_run_id,
                stage_attempt_id=claim.stage_attempt_id,
                status="EXECUTION_FAILED",
                error_class=type(exc).__name__,
                error_detail={"message": str(exc), "retryable": True},
                attempt_usage={
                    "worker": "modal",
                    "remote": True,
                    "modal_call_id": collected.modal_call_id,
                },
            )
        if result is None:
            claim = await self._scheduler.load_claim(collected.stage_attempt_id)
            renewed = await self._scheduler.heartbeat(
                claim,
                lease_seconds=self._attempt_lease_seconds,
            )
            if renewed:
                await self._release_collection(collected.stage_attempt_id)
            else:
                await self.reap_stale_attempts()
            return False

        claim = await self._scheduler.load_claim(collected.stage_attempt_id)
        if (
            result.stage_run_id != claim.stage_run_id
            or result.stage_attempt_id != claim.stage_attempt_id
        ):
            result = StageResult(
                stage_run_id=claim.stage_run_id,
                stage_attempt_id=claim.stage_attempt_id,
                status="EXECUTION_FAILED",
                error_class="ModalResultIdentityError",
                error_detail={
                    "message": "Modal result identity does not match the persisted attempt",
                    "retryable": False,
                },
                attempt_usage={
                    "worker": "modal",
                    "remote": True,
                    "modal_call_id": collected.modal_call_id,
                },
            )
        committed = await self._scheduler.commit_result(claim, result)
        if committed:
            await self._scheduler.finalize_stage(claim)
        elif result.status != "EXECUTION_FAILED":
            await self._mark_collection_rejected(collected.stage_attempt_id)
        return True

    async def run_until_quiet(self, max_events: int = 1000) -> tuple[int, int]:
        dispatched = 0
        collected = 0
        while dispatched + collected < max_events:
            made_progress = False
            if await self.dispatch_one():
                dispatched += 1
                made_progress = True
            if await self.collect_one():
                collected += 1
                made_progress = True
            if not made_progress:
                break
        if dispatched + collected == max_events:
            raise RuntimeError("outbox event limit reached before dispatcher became quiet")
        return dispatched, collected

    async def reap_stale_attempts(self, limit: int = 100) -> int:
        if limit < 1:
            raise ValueError("limit must be positive")
        modal_calls: list[str] = []
        reaped = 0
        async with self._sessions.begin() as session:
            now = datetime.now(UTC)
            rows = (
                await session.execute(
                    select(StageAttempt, StageRun)
                    .join(StageRun, StageRun.id == StageAttempt.stage_run_id)
                    .where(
                        StageRun.status == "RUNNING",
                        StageAttempt.finished_at.is_(None),
                        StageAttempt.status.in_(
                            [
                                "RUNNING",
                                "DISPATCH_PENDING",
                                "DISPATCHING",
                                "DISPATCHED",
                                "COLLECTING",
                            ]
                        ),
                        StageAttempt.lease_expires_at.is_not(None),
                        StageAttempt.lease_expires_at <= now,
                    )
                    .order_by(StageAttempt.lease_expires_at)
                    .with_for_update(
                        of=(StageAttempt, StageRun),
                        skip_locked=True,
                    )
                    .limit(limit)
                )
            ).all()
            for attempt, run in rows:
                attempt.status = "TIMED_OUT"
                attempt.termination_reason = "LEASE_EXPIRED"
                attempt.error_class = "AttemptLeaseExpired"
                attempt.error_detail = {
                    "message": "attempt heartbeat lease expired",
                    "retryable": True,
                }
                attempt.finished_at = now
                if attempt.modal_call_id:
                    modal_calls.append(attempt.modal_call_id)
                await session.execute(
                    update(OutboxEvent)
                    .where(
                        OutboxEvent.aggregate_id == run.id,
                        OutboxEvent.event_type == "stage.dispatch.requested",
                        OutboxEvent.status.in_(["PENDING", "DISPATCHING", "DISPATCHED"]),
                        OutboxEvent.payload["stage_attempt_id"].astext
                        == str(attempt.id),
                    )
                    .values(
                        status="CANCELLED",
                        published_at=func.coalesce(OutboxEvent.published_at, now),
                        last_error={"reason": "ATTEMPT_LEASE_EXPIRED"},
                    )
                )
                attempt_count = await session.scalar(
                    select(func.count(StageAttempt.id)).where(
                        StageAttempt.stage_run_id == run.id
                    )
                )
                run.lease_owner = None
                run.lease_expires_at = None
                run.state_version += 1
                if (attempt_count or 0) < self._max_stage_attempts:
                    run.status = "READY"
                    run.available_at = now + timedelta(seconds=30)
                else:
                    run.status = "EXECUTION_FAILED"
                reaped += 1
        for modal_call_id in modal_calls:
            with suppress(Exception):
                self._gateway.cancel(modal_call_id)
        return reaped

    async def _claim_event(self) -> DispatchEventClaim | None:
        async with self._sessions.begin() as session:
            row = (
                await session.execute(
                    CLAIM_STAGE_DISPATCH_EVENT,
                    {"stale_seconds": self._stale_dispatch_seconds},
                )
            ).mappings().first()
            if row is None:
                return None
            stage_attempt_id = UUID(row["payload"]["stage_attempt_id"])
            await session.execute(
                update(StageAttempt)
                .where(
                    StageAttempt.id == stage_attempt_id,
                    StageAttempt.status.in_(["DISPATCH_PENDING", "DISPATCHING"]),
                )
                .values(status="DISPATCHING")
            )
            return DispatchEventClaim(
                event_id=row["id"],
                stage_attempt_id=stage_attempt_id,
                publish_attempts=row["publish_attempts"],
            )

    async def _record_dispatch_success(
        self,
        claim: DispatchEventClaim,
        modal_call_id: str,
    ) -> bool:
        async with self._sessions.begin() as session:
            event = await session.get(OutboxEvent, claim.event_id, with_for_update=True)
            attempt = await session.get(
                StageAttempt, claim.stage_attempt_id, with_for_update=True
            )
            if event is None or attempt is None or event.status != "DISPATCHING":
                return False
            run = await session.get(StageRun, attempt.stage_run_id, with_for_update=True)
            if run is None or not await _dispatch_allowed(session, run):
                event.status = "CANCELLED"
                event.last_error = {"reason": "CONTROL_OR_DELETION_GATE"}
                attempt.status = "CANCELLED"
                attempt.termination_reason = "CONTROL_OR_DELETION_GATE"
                attempt.finished_at = datetime.now(UTC)
                if run is not None:
                    _cancel_run(run)
                return False
            now = datetime.now(UTC)
            attempt.modal_call_id = modal_call_id
            attempt.status = "DISPATCHED"
            event.status = "DISPATCHED"
            event.dispatched_at = now
            event.published_at = now
            event.last_error = None
            return True

    async def _record_dispatch_failure(
        self,
        claim: DispatchEventClaim,
        exc: Exception,
    ) -> None:
        error = {"class": type(exc).__name__, "message": str(exc)}
        async with self._sessions.begin() as session:
            event = await session.get(OutboxEvent, claim.event_id, with_for_update=True)
            attempt = await session.get(
                StageAttempt, claim.stage_attempt_id, with_for_update=True
            )
            if event is None or attempt is None:
                return
            run = await session.get(StageRun, attempt.stage_run_id, with_for_update=True)
            if run is None:
                event.status = "FAILED"
                event.last_error = error
                return
            if not await _dispatch_allowed(session, run):
                event.status = "CANCELLED"
                event.last_error = {"reason": "CONTROL_OR_DELETION_GATE", **error}
                attempt.status = "CANCELLED"
                attempt.termination_reason = "CONTROL_OR_DELETION_GATE"
                attempt.finished_at = datetime.now(UTC)
                _cancel_run(run)
                return
            if claim.publish_attempts < self._max_dispatch_attempts:
                delay_seconds = min(300, 2 ** min(claim.publish_attempts, 8))
                event.status = "PENDING"
                event.available_at = datetime.now(UTC) + timedelta(seconds=delay_seconds)
                event.last_error = error
                attempt.status = "DISPATCH_PENDING"
                return

            attempt.status = "DISPATCH_FAILED"
            attempt.termination_reason = "DISPATCH_FAILED"
            attempt.error_class = type(exc).__name__
            attempt.error_detail = {"message": str(exc), "retryable": True}
            attempt.finished_at = datetime.now(UTC)
            event.status = "FAILED"
            event.last_error = error
            attempt_count = await session.scalar(
                select(func.count(StageAttempt.id)).where(
                    StageAttempt.stage_run_id == run.id
                )
            )
            run.lease_owner = None
            run.lease_expires_at = None
            run.state_version += 1
            if (attempt_count or 0) < self._max_stage_attempts:
                run.status = "READY"
                run.available_at = datetime.now(UTC) + timedelta(seconds=30)
            else:
                run.status = "EXECUTION_FAILED"

    async def _claim_dispatched_attempt(self) -> CollectedAttempt | None:
        async with self._sessions.begin() as session:
            row = (
                await session.execute(
                    select(StageAttempt)
                    .join(StageRun, StageRun.id == StageAttempt.stage_run_id)
                    .where(
                        StageAttempt.status == "DISPATCHED",
                        StageAttempt.modal_call_id.is_not(None),
                        StageRun.status == "RUNNING",
                        ~select(DeletionTombstone.id)
                        .where(
                            DeletionTombstone.resource_type == "project",
                            DeletionTombstone.resource_id == StageRun.project_id,
                        )
                        .exists(),
                    )
                    .order_by(StageAttempt.started_at)
                    .with_for_update(of=StageAttempt, skip_locked=True)
                    .limit(1)
                )
            ).scalar_one_or_none()
            if row is None or row.modal_call_id is None:
                return None
            row.status = "COLLECTING"
            return CollectedAttempt(
                stage_attempt_id=row.id,
                modal_call_id=row.modal_call_id,
            )

    async def _release_collection(self, stage_attempt_id: UUID) -> None:
        async with self._sessions.begin() as session:
            await session.execute(
                update(StageAttempt)
                .where(
                    StageAttempt.id == stage_attempt_id,
                    StageAttempt.status == "COLLECTING",
                )
                .values(status="DISPATCHED")
            )

    async def _mark_collection_rejected(self, stage_attempt_id: UUID) -> None:
        async with self._sessions.begin() as session:
            await session.execute(
                update(StageAttempt)
                .where(StageAttempt.id == stage_attempt_id)
                .values(
                    status="COMMIT_REJECTED",
                    termination_reason="CONDITIONAL_COMMIT_REJECTED",
                    error_class="ConditionalCommitRejected",
                    error_detail={
                        "message": "stage result failed lease/control/deletion CAS",
                        "retryable": False,
                    },
                    finished_at=func.now(),
                )
            )

    async def _cancel_tombstoned_dispatches(self) -> None:
        async with self._sessions.begin() as session:
            rows = list(
                (
                    await session.execute(
                        select(OutboxEvent, StageAttempt, StageRun)
                        .join(StageRun, StageRun.id == OutboxEvent.aggregate_id)
                        .join(
                            StageAttempt,
                            StageAttempt.id
                            == OutboxEvent.payload["stage_attempt_id"].astext.cast(
                                PGUUID(as_uuid=True)
                            ),
                        )
                        .join(
                            DeletionTombstone,
                            (DeletionTombstone.resource_type == "project")
                            & (DeletionTombstone.resource_id == StageRun.project_id),
                        )
                        .where(
                            OutboxEvent.event_type == "stage.dispatch.requested",
                            OutboxEvent.status.in_(["PENDING", "DISPATCHING"]),
                        )
                        .with_for_update(of=OutboxEvent, skip_locked=True)
                        .limit(100)
                    )
                ).all()
            )
            for event, attempt, run in rows:
                event.status = "CANCELLED"
                event.last_error = {"reason": "PROJECT_DELETION_TOMBSTONE"}
                attempt.status = "CANCELLED"
                attempt.termination_reason = "PROJECT_DELETION_TOMBSTONE"
                attempt.finished_at = datetime.now(UTC)
                if run.status == "RUNNING":
                    _cancel_run(run)

    async def _cancel_tombstoned_calls(self) -> None:
        to_cancel: list[tuple[UUID, UUID, str]] = []
        async with self._sessions.begin() as session:
            attempts = list(
                await session.scalars(
                    select(StageAttempt)
                    .join(StageRun, StageRun.id == StageAttempt.stage_run_id)
                    .join(
                        DeletionTombstone,
                        (DeletionTombstone.resource_type == "project")
                        & (DeletionTombstone.resource_id == StageRun.project_id),
                    )
                    .where(
                        StageAttempt.status.in_(["DISPATCHED", "COLLECTING"]),
                        StageAttempt.modal_call_id.is_not(None),
                    )
                    .with_for_update(of=StageAttempt, skip_locked=True)
                    .limit(100)
                )
            )
            for attempt in attempts:
                attempt.status = "CANCELLING"
                to_cancel.append(
                    (attempt.id, attempt.stage_run_id, attempt.modal_call_id or "")
                )
        for attempt_id, stage_run_id, modal_call_id in to_cancel:
            with suppress(Exception):
                self._gateway.cancel(modal_call_id)
            async with self._sessions.begin() as session:
                await session.execute(
                    update(StageAttempt)
                    .where(StageAttempt.id == attempt_id)
                    .values(
                        status="CANCELLED",
                        termination_reason="PROJECT_DELETION_TOMBSTONE",
                        finished_at=func.now(),
                    )
                )
                await session.execute(
                    update(StageRun)
                    .where(
                        StageRun.id == stage_run_id,
                        StageRun.status == "RUNNING",
                    )
                    .values(
                        status="CANCELLED",
                        state_version=StageRun.state_version + 1,
                        lease_owner=None,
                        lease_expires_at=None,
                    )
                )


async def _dispatch_allowed(session: AsyncSession, run: StageRun) -> bool:
    control = await session.get(ExecutionControl, run.project_id)
    if (
        control is None
        or control.paused
        or control.cancel_requested
        or control.hard_budget_blocked
        or control.control_version != run.observed_control_version
    ):
        return False
    tombstone = await session.scalar(
        select(DeletionTombstone.id).where(
            DeletionTombstone.resource_type == "project",
            DeletionTombstone.resource_id == run.project_id,
        )
    )
    return tombstone is None


def _cancel_run(run: StageRun) -> None:
    if run.status != "RUNNING":
        return
    run.status = "CANCELLED"
    run.state_version += 1
    run.lease_owner = None
    run.lease_expires_at = None
