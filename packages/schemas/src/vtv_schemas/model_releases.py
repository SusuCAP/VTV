from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


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
