from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field
from vtv_evaluation import (
    BenchmarkEvidence,
    BenchmarkPolicy,
    BenchmarkReport,
    GoldenDataset,
    SampleResult,
)


class BenchmarkReleaseCreate(BaseModel):
    expected_model_state_version: int = Field(ge=1)
    dataset: GoldenDataset
    policy: BenchmarkPolicy
    evidence: BenchmarkEvidence
    results: tuple[SampleResult, ...]


class BenchmarkReleaseRead(BaseModel):
    id: UUID
    workspace_id: UUID
    model_release_id: UUID
    dataset_key: str
    dataset_release: str
    dataset_fingerprint: str
    annotation_release: str
    policy_key: str
    policy_release: str
    policy_fingerprint: str
    weights_sha256: str
    runtime_fingerprint: str
    report: BenchmarkReport
    approved: bool
    failed_gates: tuple[str, ...]
    created_at: datetime
