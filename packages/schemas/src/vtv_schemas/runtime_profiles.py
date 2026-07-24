from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator


RuntimeProfileClass = Literal[
    "render-cuda12-mature",
    "render-blackwell-validated",
    "render-b300-cuda13",
    "cpu-standard",
    "audio-standard",
]


class RuntimeGateEvidence(BaseModel):
    passed: bool
    evidence_uri: str = Field(min_length=1, max_length=2048)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    completed_at: datetime


class RuntimeValidationEvidence(BaseModel):
    minimum_inference: RuntimeGateEvidence
    numerical_regression: RuntimeGateEvidence
    oom: RuntimeGateEvidence
    rollback: RuntimeGateEvidence


class RuntimeProfileCreate(BaseModel):
    profile_name: str = Field(min_length=1, max_length=128)
    profile_version: int = Field(ge=1)
    profile_class: RuntimeProfileClass
    supported_gpu_types: list[str] = Field(min_length=1)
    minimum_cuda_version: str = Field(pattern=r"^\d+\.\d+(?:\.\d+)?$")
    image_digest: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    framework_versions: dict[str, str] = Field(min_length=1)
    supported_operators: list[str] = Field(default_factory=list)
    self_test_status: Literal["PENDING", "PASS", "FAIL"] = "PENDING"
    numerical_regression_status: Literal["PENDING", "PASS", "FAIL"] = "PENDING"
    oom_test_status: Literal["PENDING", "PASS", "FAIL"] = "PENDING"
    rollback_verified: bool = False
    validation_evidence: RuntimeValidationEvidence | None = None
    validated_at: datetime | None = None
    validated_by: str | None = Field(default=None, min_length=1, max_length=128)
    notes: str | None = None

    @field_validator("supported_gpu_types", "supported_operators")
    @classmethod
    def require_unique_nonblank_values(cls, values: list[str]) -> list[str]:
        if any(not value.strip() for value in values):
            raise ValueError("runtime capability values cannot be blank")
        if len(values) != len(set(values)):
            raise ValueError("runtime capability values must be unique")
        return values

    @field_validator("framework_versions")
    @classmethod
    def require_exact_framework_lock(cls, values: dict[str, str]) -> dict[str, str]:
        if any(not key.strip() or not value.strip() for key, value in values.items()):
            raise ValueError("framework lock keys and values cannot be blank")
        mutable_refs = {"*", "dev", "head", "latest", "main", "master", "nightly"}
        if any(value.strip().lower() in mutable_refs for value in values.values()):
            raise ValueError("framework lock cannot contain mutable version references")
        return values

    @model_validator(mode="after")
    def validate_verified_snapshot(self) -> "RuntimeProfileCreate":
        statuses = (
            self.self_test_status,
            self.numerical_regression_status,
            self.oom_test_status,
        )
        has_verification = self.validated_at is not None or self.validated_by is not None
        if not has_verification:
            return self
        if self.validated_at is None or self.validated_by is None:
            raise ValueError("runtime verification requires both time and verifier")
        if self.validation_evidence is None:
            raise ValueError("verified runtime requires immutable validation evidence")
        evidence = self.validation_evidence
        if not all(
            (
                evidence.minimum_inference.passed,
                evidence.numerical_regression.passed,
                evidence.oom.passed,
                evidence.rollback.passed,
            )
        ):
            raise ValueError("verified runtime evidence contains a failed gate")
        if statuses != ("PASS", "PASS", "PASS") or not self.rollback_verified:
            raise ValueError(
                "verified runtime requires minimum inference, numerical, OOM, "
                "and rollback gates to pass"
            )
        return self


class RuntimeProfileRead(BaseModel):
    id: UUID
    profile_name: str
    profile_version: int
    profile_class: RuntimeProfileClass
    supported_gpu_types: list[str]
    minimum_cuda_version: str
    image_digest: str | None
    framework_versions: dict[str, str]
    supported_operators: list[str]
    self_test_status: Literal["PENDING", "PASS", "FAIL"]
    numerical_regression_status: Literal["PENDING", "PASS", "FAIL"]
    oom_test_status: Literal["PENDING", "PASS", "FAIL"]
    rollback_verified: bool
    validation_evidence: RuntimeValidationEvidence | None
    validated_at: datetime | None
    validated_by: str | None
    notes: str | None
    created_at: datetime
