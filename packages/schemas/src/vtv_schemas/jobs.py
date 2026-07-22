from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from .enums import JobStatus


class AssetRef(BaseModel):
    uri: str
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    media_type: str
    size_bytes: int = Field(default=1, gt=0)
    metadata: dict[str, Any] = Field(default_factory=dict)


class VariantResult(BaseModel):
    variant_no: int = Field(ge=1)
    seed: int | None = None
    output_assets: list[AssetRef] = Field(default_factory=list)
    raw_metrics: dict[str, Any] = Field(default_factory=dict)
    allocated_cost: dict[str, Any] = Field(default_factory=dict)


class DomainArtifact(BaseModel):
    document_type: str = Field(min_length=1, max_length=64, pattern=r"^[A-Z][A-Z0-9_]*$")
    schema_version: int = Field(default=1, ge=1)
    episode_id: UUID | None = None
    source_asset_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    payload: dict[str, Any]
    release_artifact_type: str | None = Field(
        default=None, max_length=64, pattern=r"^[A-Z][A-Z0-9_]*$"
    )
    release_version: int | None = Field(default=None, ge=1)
    depends_on_artifact_types: tuple[str, ...] = ()


class StageJob(BaseModel):
    stage_run_id: UUID
    stage_attempt_id: UUID
    candidate_group_id: UUID | None = None
    project_id: UUID
    episode_id: UUID | None = None
    shot_id: UUID | None = None
    idempotency_key: str = Field(min_length=1, max_length=255)
    stage_type: str
    input_assets: list[AssetRef] = Field(default_factory=list)
    output_prefix: str
    model_release_id: UUID | None = None
    runtime_profile_id: str
    observed_control_version: int = Field(ge=1)
    params: dict[str, Any] = Field(default_factory=dict)
    trace_id: str


class StageResult(BaseModel):
    stage_run_id: UUID
    stage_attempt_id: UUID
    status: Literal["OUTPUT_READY", "EXECUTION_FAILED"]
    variants: list[VariantResult] = Field(default_factory=list)
    domain_artifacts: list[DomainArtifact] = Field(default_factory=list)
    attempt_usage: dict[str, Any] = Field(default_factory=dict)
    error_class: str | None = None
    error_detail: dict[str, Any] | None = None


class JobAccepted(BaseModel):
    job_id: UUID
    status: JobStatus = JobStatus.QUEUED
    status_url: str


class JobRead(BaseModel):
    id: UUID
    project_id: UUID
    kind: str
    status: JobStatus
    progress: float = Field(ge=0, le=1)
    total_stages: int = Field(default=0, ge=0)
    completed_stages: int = Field(default=0, ge=0)
