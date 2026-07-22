from __future__ import annotations

import json
from datetime import datetime
from hashlib import sha256
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True)


class GoldenSample(FrozenModel):
    sample_id: str = Field(min_length=1, max_length=128, pattern=r"^[a-zA-Z0-9._-]+$")
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    reference_sha256s: tuple[str, ...] = ()
    duration_seconds: float = Field(gt=0)
    tags: frozenset[str] = Field(default_factory=frozenset)
    critical: bool = False

    @model_validator(mode="after")
    def validate_reference_hashes(self) -> GoldenSample:
        if any(
            len(value) != 64 or any(character not in "0123456789abcdef" for character in value)
            for value in self.reference_sha256s
        ):
            raise ValueError("reference SHA-256 values must be lowercase hexadecimal")
        if len(self.reference_sha256s) != len(set(self.reference_sha256s)):
            raise ValueError("reference SHA-256 values must be unique")
        return self


class GoldenDataset(FrozenModel):
    dataset_key: str = Field(min_length=1, max_length=128)
    release: str = Field(min_length=1, max_length=128)
    annotation_release: str = Field(min_length=1, max_length=128)
    samples: tuple[GoldenSample, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_samples(self) -> GoldenDataset:
        identifiers = [sample.sample_id for sample in self.samples]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("Golden Dataset sample IDs must be unique")
        return self

    @property
    def fingerprint(self) -> str:
        payload = self.model_dump(mode="json", exclude_none=False)
        for sample in payload["samples"]:
            sample["tags"] = sorted(sample["tags"])
        canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return sha256(canonical.encode()).hexdigest()


class BenchmarkPolicy(FrozenModel):
    policy_key: str = Field(min_length=1, max_length=128)
    release: str = Field(min_length=1, max_length=128)
    minimum_sample_count: int = Field(default=20, ge=1)
    minimum_metric_scores: dict[str, float] = Field(min_length=1)
    maximum_critical_failure_rate: float = Field(ge=0, le=1)
    maximum_human_reject_rate: float = Field(ge=0, le=1)
    maximum_cost_per_passed_second: float = Field(gt=0)
    maximum_p95_latency_seconds: float = Field(gt=0)
    confidence_z: float = Field(default=1.96, gt=0, le=5)

    @model_validator(mode="after")
    def validate_metric_thresholds(self) -> BenchmarkPolicy:
        if any(not name.strip() for name in self.minimum_metric_scores):
            raise ValueError("metric names cannot be blank")
        if any(score < 0 or score > 1 for score in self.minimum_metric_scores.values()):
            raise ValueError("minimum metric scores must be within [0, 1]")
        return self

    @property
    def fingerprint(self) -> str:
        payload = json.dumps(
            self.model_dump(mode="json", exclude_none=False),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return sha256(payload.encode()).hexdigest()


class BenchmarkEvidence(FrozenModel):
    technical_access_gate: Literal["PASS", "FAIL"]
    rollback_test: Literal["PASS", "FAIL"]
    reproducibility_test: Literal["PASS", "FAIL"]
    calibration_complete: bool
    weights_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    runtime_fingerprint: str = Field(min_length=1, max_length=512)


class SampleResult(FrozenModel):
    sample_id: str = Field(min_length=1, max_length=128)
    metric_scores: dict[str, float]
    critical_failure: bool = False
    human_rejected: bool = False
    latency_seconds: float = Field(gt=0)
    cost_usd: float = Field(ge=0)
    output_duration_seconds: float = Field(gt=0)
    error_class: str | None = Field(default=None, min_length=1, max_length=128)

    @model_validator(mode="after")
    def validate_scores(self) -> SampleResult:
        if any(score < 0 or score > 1 for score in self.metric_scores.values()):
            raise ValueError("sample metric scores must be within [0, 1]")
        return self


class MetricAggregate(FrozenModel):
    mean: float = Field(ge=0, le=1)
    confidence_lower_bound: float = Field(ge=0, le=1)
    sample_count: int = Field(ge=1)


class BenchmarkReport(FrozenModel):
    model_key: str
    model_release: str
    dataset_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    policy_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    sample_count: int = Field(ge=0)
    critical_failure_rate: float = Field(ge=0, le=1)
    human_reject_rate: float = Field(ge=0, le=1)
    cost_per_passed_output_second: float | None = Field(default=None, ge=0)
    p95_latency_seconds: float = Field(ge=0)
    metrics: dict[str, MetricAggregate]
    approved: bool
    failed_gates: tuple[str, ...]


class MetricDefinition(FrozenModel):
    metric_name: str = Field(min_length=1, max_length=100)
    metric_version: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=500)
    hard_failure_below: float | None = Field(default=None, ge=0, le=1)
    # score < hard_failure_below → candidate directly QC_FAILED, not overrideable


class EvaluatorReleaseCreate(BaseModel):
    evaluator_key: str = Field(min_length=1, max_length=64)
    release_name: str = Field(min_length=1, max_length=200)
    metric_definitions: tuple[MetricDefinition, ...] = Field(min_length=1)
    thresholds: dict[str, float] = Field(default_factory=dict)
    # thresholds: {metric_name → minimum_pass_score}

    @model_validator(mode="after")
    def validate_threshold_keys(self) -> EvaluatorReleaseCreate:
        metric_names = {m.metric_name for m in self.metric_definitions}
        for key in self.thresholds:
            if key not in metric_names:
                raise ValueError(f"threshold key {key!r} not in metric definitions")
        return self


class EvaluatorReleaseRead(BaseModel):
    id: UUID
    workspace_id: UUID
    evaluator_key: str
    release_name: str
    version: int
    status: str
    metric_definitions: list[dict]
    thresholds: dict[str, float]
    state_version: int
    created_at: datetime
    updated_at: datetime


class QcEvidenceCreate(BaseModel):
    render_variant_id: UUID
    evaluator_release_id: UUID
    results: tuple[dict, ...]
    # each dict: {metric_name, metric_version, evaluator_release, score, verdict, hard_failure}
