from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
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
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    archive_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)


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
    __table_args__ = (
        CheckConstraint("state_version >= 1", name="ck_candidate_groups_state_version"),
        CheckConstraint(
            "status IN ('OPEN', 'ADOPTED')", name="ck_candidate_groups_status"
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    shot_id: Mapped[UUID | None] = mapped_column(ForeignKey("shots.id", ondelete="CASCADE"))
    purpose: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default="OPEN")
    state_version: Mapped[int] = mapped_column(BigInteger, default=1)
    adopted_variant_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(
            "render_variants.id",
            ondelete="SET NULL",
            use_alter=True,
            name="fk_candidate_groups_adopted_variant",
        ),
        unique=True,
    )


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
    model_release_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("model_releases.id", ondelete="SET NULL")
    )
    runtime_profile_id: Mapped[str] = mapped_column(String(100))
    runtime_profile_uuid: Mapped[UUID] = mapped_column(
        ForeignKey("runtime_profiles.id", ondelete="RESTRICT"), nullable=False
    )
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
    runtime_profile_id: Mapped[UUID] = mapped_column(
        ForeignKey("runtime_profiles.id", ondelete="RESTRICT"), nullable=False
    )
    gpu_type: Mapped[str | None] = mapped_column(String(64))
    lease_owner: Mapped[str | None] = mapped_column(String(200))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    termination_reason: Mapped[str | None] = mapped_column(String(100))
    billed_gpu_seconds: Mapped[Decimal | None] = mapped_column(Numeric(14, 3))
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


class Delivery(TimestampMixin, Base):
    __tablename__ = "deliveries"
    __table_args__ = (
        UniqueConstraint("episode_id", "version"),
        CheckConstraint("version >= 1", name="ck_deliveries_version"),
        CheckConstraint("state_version >= 1", name="ck_deliveries_state_version"),
        CheckConstraint(
            "status IN ('DRAFT', 'APPROVED', 'REVOKED')",
            name="ck_deliveries_status",
        ),
        CheckConstraint(
            "(status = 'DRAFT' AND manifest IS NULL AND manifest_fingerprint IS NULL "
            "AND approved_by IS NULL AND approved_at IS NULL) OR "
            "(status IN ('APPROVED', 'REVOKED') AND manifest IS NOT NULL "
            "AND manifest_fingerprint IS NOT NULL AND approved_by IS NOT NULL "
            "AND approved_at IS NOT NULL)",
            name="ck_deliveries_approval_payload",
        ),
        Index("ix_deliveries_project_episode_status", "project_id", "episode_id", "status"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    episode_id: Mapped[UUID] = mapped_column(
        ForeignKey("episodes.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), default="DRAFT")
    state_version: Mapped[int] = mapped_column(BigInteger, default=1)
    project_state_version: Mapped[int] = mapped_column(BigInteger)
    c2pa_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    c2pa_status: Mapped[str] = mapped_column(String(16), default="NOT_REQUESTED")
    manifest: Mapped[dict | None] = mapped_column(JSONB)
    manifest_fingerprint: Mapped[str | None] = mapped_column(String(64))
    approved_by: Mapped[str | None] = mapped_column(String(200))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DeliveryAsset(Base):
    __tablename__ = "delivery_assets"
    __table_args__ = (UniqueConstraint("delivery_id", "role"),)

    delivery_id: Mapped[UUID] = mapped_column(
        ForeignKey("deliveries.id", ondelete="CASCADE"), primary_key=True
    )
    asset_id: Mapped[UUID] = mapped_column(
        ForeignKey("media_assets.id", ondelete="RESTRICT"), primary_key=True
    )
    role: Mapped[str] = mapped_column(String(32))


class RenderVariant(TimestampMixin, Base):
    __tablename__ = "render_variants"
    __table_args__ = (
        UniqueConstraint("stage_run_id", "variant_no"),
        CheckConstraint("variant_no >= 1", name="ck_render_variants_variant_no"),
        CheckConstraint(
            "status IN ('GENERATED', 'QC_PASSED', 'QC_FAILED', 'REVIEW', "
            "'ADOPTED', 'REJECTED')",
            name="ck_render_variants_status",
        ),
        Index("ix_render_variants_group_status", "candidate_group_id", "status"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    candidate_group_id: Mapped[UUID] = mapped_column(
        ForeignKey("candidate_groups.id", ondelete="CASCADE"), nullable=False
    )
    stage_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("stage_runs.id", ondelete="CASCADE"), nullable=False
    )
    variant_no: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), default="GENERATED")
    seed: Mapped[int | None] = mapped_column(BigInteger)
    output_asset_id: Mapped[UUID] = mapped_column(
        ForeignKey("media_assets.id", ondelete="RESTRICT"), nullable=False
    )
    raw_metrics: Mapped[dict] = mapped_column(JSONB, default=dict)
    allocated_cost: Mapped[dict] = mapped_column(JSONB, default=dict)


class QcResult(Base):
    __tablename__ = "qc_results"
    __table_args__ = (
        UniqueConstraint(
            "render_variant_id", "metric_name", "metric_version", "evaluator_release"
        ),
        CheckConstraint("score BETWEEN 0 AND 1", name="ck_qc_results_score"),
        CheckConstraint(
            "verdict IN ('PASS', 'FAIL', 'REVIEW')", name="ck_qc_results_verdict"
        ),
        Index("ix_qc_results_variant_verdict", "render_variant_id", "verdict"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    render_variant_id: Mapped[UUID] = mapped_column(
        ForeignKey("render_variants.id", ondelete="CASCADE"), nullable=False
    )
    metric_name: Mapped[str] = mapped_column(String(100))
    metric_version: Mapped[str] = mapped_column(String(100))
    evaluator_release: Mapped[str] = mapped_column(String(200))
    score: Mapped[float] = mapped_column(Float)
    verdict: Mapped[str] = mapped_column(String(16))
    hard_failure: Mapped[bool] = mapped_column(Boolean, default=False)
    details: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


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


class RightsRelease(TimestampMixin, Base):
    __tablename__ = "rights_releases"
    __table_args__ = (
        UniqueConstraint("project_id", "subject_type", "subject_id", "version"),
        CheckConstraint("version >= 1", name="ck_rights_releases_version"),
        CheckConstraint("state_version >= 1", name="ck_rights_releases_state_version"),
        CheckConstraint(
            "status IN ('ACTIVE', 'REVOKED')", name="ck_rights_releases_status"
        ),
        CheckConstraint(
            "commercial_scope IN ('RESEARCH_ONLY', 'COMMERCIAL')",
            name="ck_rights_releases_commercial_scope",
        ),
        CheckConstraint(
            "expires_at IS NULL OR expires_at > valid_from",
            name="ck_rights_releases_valid_window",
        ),
        Index(
            "uq_rights_releases_current_subject",
            "project_id",
            "subject_type",
            "subject_id",
            unique=True,
            postgresql_where=text("revoked_at IS NULL"),
        ),
        Index("ix_rights_releases_project_status", "project_id", "status"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    subject_type: Mapped[str] = mapped_column(String(32))
    subject_id: Mapped[str] = mapped_column(String(128))
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), default="ACTIVE")
    state_version: Mapped[int] = mapped_column(BigInteger, default=1)
    allowed_operations: Mapped[list] = mapped_column(JSONB)
    allowed_markets: Mapped[list] = mapped_column(JSONB)
    allowed_languages: Mapped[list] = mapped_column(JSONB)
    commercial_scope: Mapped[str] = mapped_column(String(32))
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    revocation_reason: Mapped[str | None] = mapped_column(Text)
    minor_guardian_consent: Mapped[bool] = mapped_column(Boolean, default=False)
    source_asset_ids: Mapped[list] = mapped_column(JSONB, default=list)
    evidence_uri: Mapped[str] = mapped_column(Text)
    evidence_sha256: Mapped[str] = mapped_column(String(64))
    supersedes_release_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("rights_releases.id", ondelete="SET NULL")
    )
    created_by: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True))

class AnalysisDocument(TimestampMixin, Base):
    __tablename__ = "analysis_documents"
    __table_args__ = (
        UniqueConstraint("source_stage_run_id", "media_asset_id", "document_type"),
        CheckConstraint("schema_version >= 1", name="ck_analysis_documents_schema_version"),
        Index("ix_analysis_documents_project_type", "project_id", "document_type"),
        Index("ix_analysis_documents_payload_gin", "payload", postgresql_using="gin"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    episode_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("episodes.id", ondelete="CASCADE")
    )
    source_stage_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("stage_runs.id", ondelete="CASCADE"), nullable=False
    )
    media_asset_id: Mapped[UUID] = mapped_column(
        ForeignKey("media_assets.id", ondelete="RESTRICT"), nullable=False
    )
    document_type: Mapped[str] = mapped_column(String(64))
    schema_version: Mapped[int] = mapped_column(Integer, default=1)
    payload: Mapped[dict] = mapped_column(JSONB)


class ModelRelease(TimestampMixin, Base):
    __tablename__ = "model_releases"
    __table_args__ = (
        UniqueConstraint("workspace_id", "model_key", "release_name"),
        CheckConstraint("state_version >= 1", name="ck_model_releases_state_version"),
        CheckConstraint(
            "license_status IN ('REVIEW', 'APPROVED', 'REJECTED')",
            name="ck_model_releases_license_status",
        ),
        CheckConstraint(
            "automation_status IN ('OBSERVE', 'CANARY', 'ACTIVE', 'DISABLED')",
            name="ck_model_releases_automation_status",
        ),
        CheckConstraint(
            "lifecycle_status IN ("
            "'EXPERIMENTAL', 'CANDIDATE', 'APPROVED_PRIMARY', "
            "'APPROVED_STABLE', 'RETIRED'"
            ")",
            name="ck_model_releases_lifecycle_status",
        ),
        CheckConstraint(
            "traffic_percent BETWEEN 0 AND 100",
            name="ck_model_releases_traffic_percent",
        ),
        Index(
            "ix_model_releases_workspace_key_status",
            "workspace_id",
            "model_key",
            "automation_status",
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    model_key: Mapped[str] = mapped_column(String(64))
    release_name: Mapped[str] = mapped_column(String(200))
    provider: Mapped[str] = mapped_column(String(100))
    endpoint: Mapped[str] = mapped_column(Text)
    license_id: Mapped[str] = mapped_column(String(200))
    license_status: Mapped[str] = mapped_column(String(32), default="REVIEW")
    automation_status: Mapped[str] = mapped_column(String(32), default="OBSERVE")
    lifecycle_status: Mapped[str] = mapped_column(String(32), default="EXPERIMENTAL")
    traffic_percent: Mapped[int] = mapped_column(Integer, default=0)
    state_version: Mapped[int] = mapped_column(BigInteger, default=1)
    model_card_uri: Mapped[str] = mapped_column(Text)
    config_json: Mapped[dict] = mapped_column("config", JSONB, default=dict)
    fallback_release_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("model_releases.id", ondelete="SET NULL")
    )
    reviewed_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_benchmark_release_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("benchmark_releases.id", ondelete="SET NULL", use_alter=True)
    )


class BenchmarkRelease(Base):
    __tablename__ = "benchmark_releases"
    __table_args__ = (
        UniqueConstraint(
            "model_release_id",
            "dataset_fingerprint",
            "policy_fingerprint",
            "weights_sha256",
        ),
        CheckConstraint(
            "approved = FALSE OR jsonb_array_length(failed_gates) = 0",
            name="ck_benchmark_releases_approved_has_no_failures",
        ),
        Index("ix_benchmark_releases_workspace_model", "workspace_id", "model_release_id"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    model_release_id: Mapped[UUID] = mapped_column(
        ForeignKey("model_releases.id", ondelete="CASCADE"), nullable=False
    )
    dataset_key: Mapped[str] = mapped_column(String(128))
    dataset_release: Mapped[str] = mapped_column(String(128))
    dataset_fingerprint: Mapped[str] = mapped_column(String(64))
    annotation_release: Mapped[str] = mapped_column(String(128))
    policy_key: Mapped[str] = mapped_column(String(128))
    policy_release: Mapped[str] = mapped_column(String(128))
    policy_fingerprint: Mapped[str] = mapped_column(String(64))
    weights_sha256: Mapped[str] = mapped_column(String(64))
    runtime_fingerprint: Mapped[str] = mapped_column(Text)
    evidence: Mapped[dict] = mapped_column(JSONB)
    report: Mapped[dict] = mapped_column(JSONB)
    approved: Mapped[bool] = mapped_column(Boolean)
    failed_gates: Mapped[list] = mapped_column(JSONB, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class BenchmarkSampleResult(Base):
    __tablename__ = "benchmark_sample_results"
    __table_args__ = (UniqueConstraint("benchmark_release_id", "sample_id"),)

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    benchmark_release_id: Mapped[UUID] = mapped_column(
        ForeignKey("benchmark_releases.id", ondelete="CASCADE"), nullable=False
    )
    sample_id: Mapped[str] = mapped_column(String(128))
    source_sha256: Mapped[str] = mapped_column(String(64))
    critical: Mapped[bool] = mapped_column(Boolean, default=False)
    result: Mapped[dict] = mapped_column(JSONB)


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
    __table_args__ = (
        Index("ix_outbox_unpublished", "published_at", "created_at"),
        Index("ix_outbox_dispatch", "status", "available_at", "created_at"),
        UniqueConstraint("dedupe_key", name="uq_outbox_events_dedupe_key"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    aggregate_type: Mapped[str] = mapped_column(String(64))
    aggregate_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True))
    event_type: Mapped[str] = mapped_column(String(100))
    payload: Mapped[dict] = mapped_column(JSONB)
    dedupe_key: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(32), default="PENDING")
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[dict | None] = mapped_column(JSONB)
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


class EvaluatorRelease(TimestampMixin, Base):
    __tablename__ = "evaluator_releases"
    __table_args__ = (
        UniqueConstraint("workspace_id", "evaluator_key", "version"),
        CheckConstraint("version >= 1", name="ck_evaluator_releases_version"),
        CheckConstraint(
            "status IN ('ACTIVE', 'DEPRECATED')",
            name="ck_evaluator_releases_status",
        ),
        CheckConstraint("state_version >= 1", name="ck_evaluator_releases_state_version"),
        Index("ix_evaluator_releases_key_status", "workspace_id", "evaluator_key", "status"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    evaluator_key: Mapped[str] = mapped_column(String(64))
    release_name: Mapped[str] = mapped_column(String(200))
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), default="ACTIVE")
    metric_definitions: Mapped[list] = mapped_column(JSONB, default=list)
    thresholds: Mapped[dict] = mapped_column(JSONB, default=dict)
    state_version: Mapped[int] = mapped_column(BigInteger, default=1)


# Register migration-owned governance tables in Base.metadata for schema
# inspection and future repository mappings. Importing at the end avoids a
# circular dependency while DeclarativeBase and all operational models exist.
from . import governance_tables as _governance_tables  # noqa: E402,F401
