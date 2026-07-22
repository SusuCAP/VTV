from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from .enums import JobStatus


class AssetRef(BaseModel):
    uri: str
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    media_type: str


class VariantResult(BaseModel):
    variant_no: int = Field(ge=1)
    seed: int | None = None
    output_assets: list[AssetRef] = Field(default_factory=list)
    raw_metrics: dict[str, Any] = Field(default_factory=dict)
    allocated_cost: dict[str, Any] = Field(default_factory=dict)


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
