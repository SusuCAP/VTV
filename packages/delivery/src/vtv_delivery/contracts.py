from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from hashlib import sha256
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

SHA256_PATTERN = r"^[0-9a-f]{64}$"


class DeliveredAsset(BaseModel):
    asset_id: UUID
    role: Literal[
        "SOURCE_VIDEO",
        "MASTER_VIDEO",
        "SUBTITLE_SRT",
        "SUBTITLE_VTT",
        "QUALITY_REPORT",
        "SHOT_LIST",
        "POSTER",
        "TRAILER",
        "AD_CUT",
    ]
    object_uri: str = Field(min_length=1)
    sha256: str = Field(pattern=SHA256_PATTERN)
    size_bytes: int = Field(gt=0)
    content_type: str = Field(min_length=1)
    metadata: dict = Field(default_factory=dict)


class EditStageEvidence(BaseModel):
    stage_run_id: UUID
    stage_type: str = Field(min_length=1, max_length=64)
    input_sha256s: tuple[str, ...] = ()
    output_sha256s: tuple[str, ...] = Field(min_length=1)
    parameters_sha256: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def validate_hashes(self) -> EditStageEvidence:
        hashes = (*self.input_sha256s, *self.output_sha256s)
        if any(
            len(value) != 64 or any(c not in "0123456789abcdef" for c in value)
            for value in hashes
        ):
            raise ValueError("stage input and output hashes must be lowercase SHA-256")
        if len(self.output_sha256s) != len(set(self.output_sha256s)):
            raise ValueError("stage output hashes must be unique")
        return self


class ModelEvidence(BaseModel):
    model_release_id: UUID
    model_key: str = Field(min_length=1, max_length=64)
    release_name: str = Field(min_length=1, max_length=200)
    weights_sha256: str = Field(pattern=SHA256_PATTERN)
    seed: int | None = None


class ApprovalEvidence(BaseModel):
    subject_type: Literal["ARTIFACT_RELEASE", "CANDIDATE_GROUP", "DELIVERY"]
    subject_id: UUID
    decision: Literal["CONFIRMED", "ADOPTED", "APPROVED"]
    actor_id: str = Field(min_length=1, max_length=200)
    state_version: int = Field(ge=1)
    decided_at: datetime


class QcEvidence(BaseModel):
    metric_name: str = Field(min_length=1, max_length=100)
    metric_version: str = Field(min_length=1, max_length=100)
    evaluator_release: str = Field(min_length=1, max_length=200)
    score: float = Field(ge=0, le=1)
    verdict: Literal["PASS", "REVIEW"]
    hard_failure: bool = False

    @model_validator(mode="after")
    def reject_failed_delivery(self) -> QcEvidence:
        if self.hard_failure:
            raise ValueError("delivery QC evidence cannot contain hard failures")
        return self


class ShotDeliveryEntry(BaseModel):
    shot_id: UUID
    shot_no: int = Field(ge=1)
    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)
    route: Literal["L0", "L1", "L2", "L3", "L4", "L5"]
    adopted_variant_id: UUID | None = None
    output_asset_id: UUID | None = None
    qc_verdict: Literal["PASS", "REVIEW", "SOURCE_UNCHANGED"]


class CostSummary(BaseModel):
    currency: str = Field(default="USD", pattern=r"^[A-Z]{3}$")
    total: Decimal = Field(ge=0, decimal_places=6)
    by_stage: dict[str, Decimal] = Field(default_factory=dict)
    provider_usage: tuple[dict, ...] = ()

    @model_validator(mode="after")
    def validate_stage_costs(self) -> CostSummary:
        if any(value < 0 for value in self.by_stage.values()):
            raise ValueError("stage costs must be non-negative")
        if sum(self.by_stage.values(), Decimal()) > self.total:
            raise ValueError("stage costs cannot exceed total cost")
        return self


class DeliveryManifest(BaseModel):
    schema_version: Literal["vtv.delivery-manifest.v1"] = "vtv.delivery-manifest.v1"
    delivery_id: UUID
    workspace_id: UUID
    project_id: UUID
    episode_id: UUID
    project_state_version: int = Field(ge=1)
    generated_at: datetime
    assets: tuple[DeliveredAsset, ...] = Field(min_length=4)
    edit_chain: tuple[EditStageEvidence, ...] = Field(min_length=1)
    models: tuple[ModelEvidence, ...] = ()
    approvals: tuple[ApprovalEvidence, ...] = Field(min_length=1)
    qc: tuple[QcEvidence, ...] = Field(min_length=1)
    shots: tuple[ShotDeliveryEntry, ...] = Field(min_length=1)
    cost: CostSummary
    final_encoding: dict
    c2pa_status: Literal["NOT_REQUESTED", "PENDING", "EMBEDDED", "FAILED"]

    @model_validator(mode="after")
    def validate_delivery_closure(self) -> DeliveryManifest:
        roles = [asset.role for asset in self.assets]
        required = {"SOURCE_VIDEO", "MASTER_VIDEO", "QUALITY_REPORT", "SHOT_LIST"}
        if not required.issubset(roles):
            raise ValueError("delivery requires source, master, quality report, and shot list")
        if "SUBTITLE_SRT" not in roles and "SUBTITLE_VTT" not in roles:
            raise ValueError("delivery requires at least one subtitle sidecar")
        if len(roles) != len(set(roles)):
            raise ValueError("delivery asset roles must be unique")
        asset_ids = [asset.asset_id for asset in self.assets]
        if len(asset_ids) != len(set(asset_ids)):
            raise ValueError("delivery assets must be unique")
        if [shot.shot_no for shot in self.shots] != list(range(1, len(self.shots) + 1)):
            raise ValueError("shot numbers must be contiguous from one")
        for previous, current in zip(self.shots, self.shots[1:], strict=False):
            if previous.end_ms != current.start_ms:
                raise ValueError("shot list must be contiguous and non-overlapping")
        if any(shot.end_ms <= shot.start_ms for shot in self.shots):
            raise ValueError("shot end must be after start")
        output_hashes = {value for stage in self.edit_chain for value in stage.output_sha256s}
        master_hash = next(asset.sha256 for asset in self.assets if asset.role == "MASTER_VIDEO")
        if master_hash not in output_hashes:
            raise ValueError("master must be traceable to an edit stage output")
        return self

    @property
    def fingerprint(self) -> str:
        payload = self.model_dump(mode="json", exclude={"generated_at"})
        canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return sha256(canonical.encode()).hexdigest()


class DeliveryManifestBuilder:
    @staticmethod
    def build(**values: object) -> DeliveryManifest:
        return DeliveryManifest.model_validate(values)


class DeliveryCreate(BaseModel):
    episode_id: UUID
    master_asset_id: UUID
    subtitle_asset_ids: tuple[UUID, ...] = Field(min_length=1, max_length=2)
    quality_report_asset_id: UUID
    shot_list_asset_id: UUID
    additional_asset_ids: tuple[UUID, ...] = ()
    expected_project_state_version: int = Field(ge=1)
    c2pa_requested: bool = False

    @model_validator(mode="after")
    def unique_assets(self) -> DeliveryCreate:
        values = (
            self.master_asset_id,
            *self.subtitle_asset_ids,
            self.quality_report_asset_id,
            self.shot_list_asset_id,
            *self.additional_asset_ids,
        )
        if len(values) != len(set(values)):
            raise ValueError("delivery asset IDs must be unique")
        return self


class DeliveryApprove(BaseModel):
    expected_state_version: int = Field(ge=1)
    actor_id: str = Field(min_length=1, max_length=200)


class DeliveryRead(BaseModel):
    id: UUID
    workspace_id: UUID
    project_id: UUID
    episode_id: UUID
    version: int = Field(ge=1)
    status: Literal["DRAFT", "APPROVED", "REVOKED"]
    state_version: int = Field(ge=1)
    c2pa_status: Literal[
        "NOT_REQUESTED", "PENDING", "SIGNING", "SIGNED", "SIGN_FAILED"
    ] = "NOT_REQUESTED"
    manifest_fingerprint: str | None = Field(default=None, pattern=SHA256_PATTERN)
    manifest: DeliveryManifest | None = None
    approved_by: str | None = None
    approved_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class DeliveryEvidenceRequest(BaseModel):
    source_video_sha256: str = Field(pattern=SHA256_PATTERN)
    master_video_sha256: str = Field(pattern=SHA256_PATTERN)
    project_state_version: int = Field(ge=1)
    duration_ms: int = Field(gt=0)
    edit_chain: tuple[EditStageEvidence, ...] = Field(min_length=1)
    models: tuple[ModelEvidence, ...] = ()
    qc: tuple[QcEvidence, ...] = ()
    shots: tuple[ShotDeliveryEntry, ...] = Field(min_length=1)
    cost: CostSummary
    final_encoding: dict

    @model_validator(mode="after")
    def validate_evidence(self) -> DeliveryEvidenceRequest:
        if [shot.shot_no for shot in self.shots] != list(range(1, len(self.shots) + 1)):
            raise ValueError("shot numbers must be contiguous from one")
        if self.shots[0].start_ms != 0 or self.shots[-1].end_ms != self.duration_ms:
            raise ValueError("shot list must span the full episode")
        for previous, current in zip(self.shots, self.shots[1:], strict=False):
            if previous.end_ms != current.start_ms:
                raise ValueError("shot list must be contiguous and non-overlapping")
        output_hashes = {value for stage in self.edit_chain for value in stage.output_sha256s}
        if self.master_video_sha256 not in output_hashes:
            raise ValueError("master must be traceable to edit chain outputs")
        return self


class C2paContentCredentials(BaseModel):
    """Placeholder content credentials generated by the passthrough signer."""

    schema_version: Literal["vtv.c2pa-credentials.v1"] = "vtv.c2pa-credentials.v1"
    delivery_id: UUID
    manifest_fingerprint: str = Field(pattern=SHA256_PATTERN)
    signer: str = Field(min_length=1, max_length=200)
    signed_at: datetime
    assertions: tuple[str, ...] = ()
    # Placeholder: real C2PA SDK would embed this into the master video
    credential_uri: str = Field(min_length=1)


class C2paSignRequest(BaseModel):
    delivery_id: UUID
    manifest_fingerprint: str = Field(pattern=SHA256_PATTERN)
    master_object_uri: str = Field(min_length=1)
    output_prefix: str = Field(min_length=1)
    signer_id: str = Field(default="vtv.passthrough-signer.v1", min_length=1)


class C2paSignResult(BaseModel):
    delivery_id: UUID
    manifest_fingerprint: str = Field(pattern=SHA256_PATTERN)
    credentials: C2paContentCredentials
    credential_asset_sha256: str = Field(pattern=SHA256_PATTERN)
    credential_asset_uri: str = Field(min_length=1)
    credential_size_bytes: int = Field(gt=0)


class DeliveryPackageAsset(BaseModel):
    role: str
    object_uri: str
    sha256: str
    size_bytes: int
    content_type: str
    download_url: str  # 15-minute presigned URL (passthrough: object_uri itself)


class DeliveryPackage(BaseModel):
    delivery_id: UUID
    manifest_fingerprint: str
    assets: list[DeliveryPackageAsset]
    expires_at: datetime  # presigned URLs expire at this time


class DeliveryRevoke(BaseModel):
    reason: str = Field(min_length=1, max_length=200)
    actor_id: str = Field(min_length=1, max_length=200)
