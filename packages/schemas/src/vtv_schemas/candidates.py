from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

VariantStatus = Literal[
    "GENERATED", "QC_PASSED", "QC_FAILED", "REVIEW", "ADOPTED", "REJECTED"
]
CandidateGroupStatus = Literal["OPEN", "ADOPTED"]
QcVerdict = Literal["PASS", "FAIL", "REVIEW"]


class QcMetricCreate(BaseModel):
    metric_name: str = Field(min_length=1, max_length=100)
    metric_version: str = Field(min_length=1, max_length=100)
    evaluator_release: str = Field(min_length=1, max_length=200)
    score: float = Field(ge=0, le=1)
    verdict: QcVerdict
    hard_failure: bool = False
    details: dict = Field(default_factory=dict)


class CandidateQcCreate(BaseModel):
    metrics: tuple[QcMetricCreate, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_metric_evidence(self) -> CandidateQcCreate:
        keys = [
            (item.metric_name, item.metric_version, item.evaluator_release)
            for item in self.metrics
        ]
        if len(keys) != len(set(keys)):
            raise ValueError("QC metric evidence must be unique")
        return self


class QcMetricRead(QcMetricCreate):
    id: UUID
    created_at: datetime


class CandidateVariantRead(BaseModel):
    id: UUID
    candidate_group_id: UUID
    stage_run_id: UUID
    variant_no: int
    status: VariantStatus
    seed: int | None = None
    output_asset_id: UUID
    raw_metrics: dict
    allocated_cost: dict
    qc_results: tuple[QcMetricRead, ...] = ()
    created_at: datetime
    updated_at: datetime


class CandidateGroupRead(BaseModel):
    id: UUID
    project_id: UUID
    shot_id: UUID | None = None
    purpose: str
    status: CandidateGroupStatus
    state_version: int
    adopted_variant_id: UUID | None = None
    variants: tuple[CandidateVariantRead, ...] = ()
    created_at: datetime
    updated_at: datetime


class CandidateAdopt(BaseModel):
    variant_id: UUID
    expected_state_version: int = Field(ge=1)
    actor_id: UUID


class CandidateAdoptRequest(BaseModel):
    actor_id: str = Field(min_length=1, max_length=200)
    reason: str = Field(default="manual-adoption", min_length=1, max_length=500)
    override_qc_failure: bool = False


class CandidateAdoptResult(BaseModel):
    variant_id: UUID
    candidate_group_id: UUID
    previous_status: str
    new_status: str
    actor_id: str
    adopted_at: datetime
