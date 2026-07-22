from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Workspace(TimestampMixin, Base):
    __tablename__ = "workspaces"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(200))


class Project(TimestampMixin, Base):
    __tablename__ = "projects"
    __table_args__ = (
        CheckConstraint("budget_warning_at >= 0", name="ck_projects_budget_warning_nonnegative"),
        CheckConstraint(
            "budget_hard_limit > 0 AND budget_warning_at <= budget_hard_limit",
            name="ck_projects_budget_limits",
        ),
        Index("ix_projects_workspace_status", "workspace_id", "status"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(200))
    target_market: Mapped[str] = mapped_column(String(16))
    locale: Mapped[str] = mapped_column(String(35))
    timezone: Mapped[str] = mapped_column(String(64), default="UTC")
    quality_profile: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(40), default="DRAFT")
    state_version: Mapped[int] = mapped_column(BigInteger, default=1)
    budget_currency: Mapped[str] = mapped_column(String(3), default="USD")
    budget_warning_at: Mapped[Decimal] = mapped_column(Numeric(14, 4))
    budget_hard_limit: Mapped[Decimal] = mapped_column(Numeric(14, 4))
    output_spec: Mapped[dict] = mapped_column(JSONB)


class Episode(TimestampMixin, Base):
    __tablename__ = "episodes"
    __table_args__ = (UniqueConstraint("project_id", "episode_no"),)

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    episode_no: Mapped[int] = mapped_column(Integer)
    title: Mapped[str | None] = mapped_column(String(200))
    source_asset_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("media_assets.id", ondelete="SET NULL")
    )
    duration_ms: Mapped[int | None] = mapped_column(BigInteger)


class UploadSession(TimestampMixin, Base):
    __tablename__ = "upload_sessions"
    __table_args__ = (
        UniqueConstraint("workspace_id", "provider_upload_id"),
        Index("ix_upload_sessions_project_status", "project_id", "status"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    episode_no: Mapped[int | None] = mapped_column(Integer)
    filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(200))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    part_size_bytes: Mapped[int] = mapped_column(BigInteger)
    declared_sha256: Mapped[str] = mapped_column(String(64))
    object_key: Mapped[str] = mapped_column(Text, unique=True)
    provider_upload_id: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="UPLOADING")
    completed_parts: Mapped[list] = mapped_column(JSONB, default=list)
    object_checksum_sha256: Mapped[str | None] = mapped_column(String(64))
    episode_id: Mapped[UUID | None] = mapped_column(ForeignKey("episodes.id", ondelete="SET NULL"))
    media_asset_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("media_assets.id", ondelete="SET NULL")
    )
    ingest_job_id: Mapped[UUID | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"))


class Shot(TimestampMixin, Base):
    __tablename__ = "shots"
    __table_args__ = (
        UniqueConstraint("episode_id", "shot_no"),
        CheckConstraint("end_ms > start_ms", name="ck_shots_positive_duration"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    episode_id: Mapped[UUID] = mapped_column(
        ForeignKey("episodes.id", ondelete="CASCADE"), nullable=False
    )
    shot_no: Mapped[int] = mapped_column(Integer)
    start_ms: Mapped[int] = mapped_column(BigInteger)
    end_ms: Mapped[int] = mapped_column(BigInteger)
    route: Mapped[str | None] = mapped_column(String(8))
    reason_codes: Mapped[list] = mapped_column(JSONB, default=list)


class ExecutionControl(TimestampMixin, Base):
    __tablename__ = "execution_controls"

    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    )
    control_version: Mapped[int] = mapped_column(BigInteger, default=1)
    paused: Mapped[bool] = mapped_column(Boolean, default=False)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    hard_budget_blocked: Mapped[bool] = mapped_column(Boolean, default=False)


class Job(TimestampMixin, Base):
    __tablename__ = "jobs"
    __table_args__ = (
        UniqueConstraint("project_id", "idempotency_key"),
        Index("ix_jobs_project_status", "project_id", "status"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), default="QUEUED")
    idempotency_key: Mapped[str] = mapped_column(String(255))
    total_stages: Mapped[int] = mapped_column(Integer, default=0)
    completed_stages: Mapped[int] = mapped_column(Integer, default=0)
    error_detail: Mapped[dict | None] = mapped_column(JSONB)


class CandidateGroup(TimestampMixin, Base):
    __tablename__ = "candidate_groups"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    shot_id: Mapped[UUID | None] = mapped_column(ForeignKey("shots.id", ondelete="CASCADE"))
    purpose: Mapped[str] = mapped_column(String(64))
    adopted_variant_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), unique=True)


class StageRun(TimestampMixin, Base):
    __tablename__ = "stage_runs"
    __table_args__ = (
        UniqueConstraint("project_id", "idempotency_key"),
        Index("ix_stage_runs_claim", "status", "available_at", "priority"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    job_id: Mapped[UUID | None] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"))
    episode_id: Mapped[UUID | None] = mapped_column(ForeignKey("episodes.id", ondelete="CASCADE"))
    shot_id: Mapped[UUID | None] = mapped_column(ForeignKey("shots.id", ondelete="CASCADE"))
    candidate_group_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("candidate_groups.id", ondelete="SET NULL")
    )
    stage_type: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), default="PENDING")
    idempotency_key: Mapped[str] = mapped_column(String(255))
    model_release_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    runtime_profile_id: Mapped[str] = mapped_column(String(100))
    state_version: Mapped[int] = mapped_column(BigInteger, default=1)
    observed_control_version: Mapped[int] = mapped_column(BigInteger)
    priority: Mapped[int] = mapped_column(Integer, default=0)
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    lease_owner: Mapped[str | None] = mapped_column(String(200))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    params: Mapped[dict] = mapped_column(JSONB, default=dict)


class StageDependency(Base):
    __tablename__ = "stage_dependencies"

    stage_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("stage_runs.id", ondelete="CASCADE"), primary_key=True
    )
    depends_on_stage_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("stage_runs.id", ondelete="CASCADE"), primary_key=True
    )


class StageAttempt(TimestampMixin, Base):
    __tablename__ = "stage_attempts"
    __table_args__ = (UniqueConstraint("stage_run_id", "attempt_no"),)

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    stage_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("stage_runs.id", ondelete="CASCADE"), nullable=False
    )
    attempt_no: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32), default="RUNNING")
    modal_call_id: Mapped[str | None] = mapped_column(String(200))
    worker_id: Mapped[str | None] = mapped_column(String(200))
    lease_token: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), default=uuid4)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    usage: Mapped[dict] = mapped_column(JSONB, default=dict)
    cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(14, 6))
    error_class: Mapped[str | None] = mapped_column(String(100))
    error_detail: Mapped[dict | None] = mapped_column(JSONB)


class MediaAsset(TimestampMixin, Base):
    __tablename__ = "media_assets"
    __table_args__ = (UniqueConstraint("workspace_id", "sha256", "object_uri"),)

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    source_stage_run_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("stage_runs.id", ondelete="SET NULL")
    )
    object_uri: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(String(64))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    content_type: Mapped[str] = mapped_column(String(200))
    metadata_json: Mapped[dict] = mapped_column("metadata", JSONB, default=dict)


class ArtifactRelease(TimestampMixin, Base):
    __tablename__ = "artifact_releases"
    __table_args__ = (
        UniqueConstraint("project_id", "artifact_type", "version"),
        CheckConstraint("version >= 1", name="ck_artifact_releases_version"),
        CheckConstraint("state_version >= 1", name="ck_artifact_releases_state_version"),
        CheckConstraint(
            "status IN ('DRAFT', 'CONFIRMED', 'RELEASED', 'STALE')",
            name="ck_artifact_releases_status",
        ),
        Index("ix_artifact_releases_project_type_status", "project_id", "artifact_type", "status"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    artifact_type: Mapped[str] = mapped_column(String(64))
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32), default="DRAFT")
    state_version: Mapped[int] = mapped_column(BigInteger, default=1)
    content_asset_id: Mapped[UUID] = mapped_column(
        ForeignKey("media_assets.id", ondelete="RESTRICT"), nullable=False
    )
    supersedes_release_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("artifact_releases.id", ondelete="SET NULL")
    )
    confirmed_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    stale_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ArtifactReleaseDependency(Base):
    __tablename__ = "artifact_release_dependencies"
    __table_args__ = (
        CheckConstraint(
            "upstream_release_id <> downstream_release_id",
            name="ck_artifact_release_dependencies_not_self",
        ),
    )

    upstream_release_id: Mapped[UUID] = mapped_column(
        ForeignKey("artifact_releases.id", ondelete="CASCADE"), primary_key=True
    )
    downstream_release_id: Mapped[UUID] = mapped_column(
        ForeignKey("artifact_releases.id", ondelete="CASCADE"), primary_key=True
    )


class OrphanAsset(TimestampMixin, Base):
    __tablename__ = "orphan_assets"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    stage_attempt_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("stage_attempts.id", ondelete="SET NULL")
    )
    object_uri: Mapped[str] = mapped_column(Text)
    reason: Mapped[str] = mapped_column(String(100))
    delete_after: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class OutboxEvent(TimestampMixin, Base):
    __tablename__ = "outbox_events"
    __table_args__ = (Index("ix_outbox_unpublished", "published_at", "created_at"),)

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    aggregate_type: Mapped[str] = mapped_column(String(64))
    aggregate_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True))
    event_type: Mapped[str] = mapped_column(String(100))
    payload: Mapped[dict] = mapped_column(JSONB)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    publish_attempts: Mapped[int] = mapped_column(Integer, default=0)


class DeletionTombstone(TimestampMixin, Base):
    __tablename__ = "deletion_tombstones"
    __table_args__ = (UniqueConstraint("resource_type", "resource_id"),)

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    resource_type: Mapped[str] = mapped_column(String(64))
    resource_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True))
    requested_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    reason: Mapped[str | None] = mapped_column(Text)
