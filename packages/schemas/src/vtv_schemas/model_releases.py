import re
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, HttpUrl, field_validator, model_validator


class ModelReleaseCreate(BaseModel):
    model_key: str = Field(min_length=1, max_length=64, pattern=r"^[A-Z][A-Z0-9_]*$")
    release_name: str = Field(min_length=1, max_length=200)
    provider: str = Field(min_length=1, max_length=100)
    endpoint: str = Field(min_length=1)
    license_id: str = Field(min_length=1, max_length=200)
    model_card_uri: str = Field(min_length=1)
    config: dict[str, Any] = Field(default_factory=dict)
    fallback_release_id: UUID | None = None


class ModelLicenseReview(BaseModel):
    decision: Literal["APPROVED", "REJECTED"]
    actor_id: UUID
    expected_state_version: int = Field(ge=1)


class ModelAutomationUpdate(BaseModel):
    target: Literal["OBSERVE", "CANARY", "ACTIVE", "DISABLED"]
    traffic_percent: int = Field(ge=0, le=100)
    expected_state_version: int = Field(ge=1)


class ModelLifecycleUpdate(BaseModel):
    target: Literal[
        "CANDIDATE",
        "APPROVED_PRIMARY",
        "APPROVED_STABLE",
        "RETIRED",
    ]
    actor_id: UUID
    expected_state_version: int = Field(ge=1)


class ModelAccessProfileCreate(BaseModel):
    profile_version: int = Field(ge=1)
    access_kind: Literal["LOCAL_WEIGHTS", "REMOTE_API"]
    source_url: HttpUrl
    code_commit: str | None = Field(default=None, pattern=r"^[a-f0-9]{40,64}$")
    runtime_profile_id: UUID
    image_digest: str | None = Field(default=None, pattern=r"^sha256:[a-f0-9]{64}$")
    weight_download_url: HttpUrl | None = None
    weight_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    checkpoint_filename: str | None = Field(default=None, min_length=1, max_length=512)
    provider_model_id: str | None = Field(default=None, min_length=1, max_length=256)
    provider_lifecycle: Literal["PREVIEW", "GA", "DEPRECATED"] | None = None
    required_packages: list[str] = Field(default_factory=list)
    min_cuda_version: str = Field(pattern=r"^\d+\.\d+(?:\.\d+)?$")
    min_vram_gib: int | None = Field(default=None, ge=1)
    launch_command: str | None = Field(default=None, min_length=1)
    reproducibility_config: dict[str, Any] = Field(default_factory=dict)
    availability_status: Literal[
        "AVAILABLE",
        "GATED",
        "UNRELEASED",
        "BROKEN",
        "OOM_RISK",
    ]
    self_test_status: Literal["PENDING", "PASS", "FAIL"] = "PENDING"
    rollback_verified: bool = False
    verified_at: datetime | None = None

    @field_validator("required_packages")
    @classmethod
    def require_exact_dependency_versions(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("dependency lock entries must be unique")

        def is_immutable(value: str) -> bool:
            if re.fullmatch(r"sha256:[a-f0-9]{64}", value):
                return True
            if value.startswith("git+"):
                return re.search(r"@[a-f0-9]{40,64}(?:#.*)?$", value) is not None
            return (
                re.fullmatch(
                    r"[A-Za-z0-9_.-]+(?:\[[A-Za-z0-9_,.-]+\])?==\S+",
                    value,
                )
                is not None
            )

        unlocked = [
            value
            for value in values
            if not is_immutable(value)
        ]
        if unlocked:
            raise ValueError(
                "dependencies must use exact versions, immutable git refs, or SHA-256"
            )
        return values

    @model_validator(mode="after")
    def validate_available_snapshot(self) -> "ModelAccessProfileCreate":
        if self.availability_status != "AVAILABLE":
            return self
        required = {
            "image_digest": self.image_digest,
            "launch_command": self.launch_command,
            "verified_at": self.verified_at,
        }
        missing = [name for name, value in required.items() if not value]
        if missing:
            raise ValueError(f"AVAILABLE access profile is missing: {', '.join(missing)}")
        if self.self_test_status != "PASS" or not self.rollback_verified:
            raise ValueError(
                "AVAILABLE access profile requires passed self-test and rollback verification"
            )
        if not self.required_packages:
            raise ValueError("AVAILABLE access profile requires an exact dependency lock")
        if not self.reproducibility_config.get("runtime_fingerprint"):
            raise ValueError(
                "AVAILABLE access profile requires a runtime fingerprint"
            )
        if self.access_kind == "LOCAL_WEIGHTS":
            local_required = {
                "code_commit": self.code_commit,
                "weight_download_url": self.weight_download_url,
                "weight_sha256": self.weight_sha256,
                "checkpoint_filename": self.checkpoint_filename,
            }
            local_missing = [name for name, value in local_required.items() if not value]
            if local_missing:
                raise ValueError(
                    "AVAILABLE local model is missing: " + ", ".join(local_missing)
                )
        elif not self.provider_model_id or not self.provider_lifecycle:
            raise ValueError(
                "AVAILABLE remote model requires provider model ID and lifecycle"
            )
        return self


class ModelAccessProfileRead(ModelAccessProfileCreate):
    id: UUID
    model_release_id: UUID
    created_at: datetime


class ModelReleaseRead(BaseModel):
    id: UUID
    workspace_id: UUID
    model_key: str
    release_name: str
    provider: str
    endpoint: str
    license_id: str
    license_status: Literal["REVIEW", "APPROVED", "REJECTED"]
    automation_status: Literal["OBSERVE", "CANARY", "ACTIVE", "DISABLED"]
    lifecycle_status: Literal[
        "EXPERIMENTAL",
        "CANDIDATE",
        "APPROVED_PRIMARY",
        "APPROVED_STABLE",
        "RETIRED",
    ] = "EXPERIMENTAL"
    traffic_percent: int
    state_version: int
    model_card_uri: str
    config: dict[str, Any]
    fallback_release_id: UUID | None = None
    reviewed_by: UUID | None = None
    reviewed_at: datetime | None = None
    approved_benchmark_release_id: UUID | None = None
    created_at: datetime
    updated_at: datetime
