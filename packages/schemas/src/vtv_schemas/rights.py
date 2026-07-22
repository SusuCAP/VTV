from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from urllib.parse import urlparse
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

SubjectType = Literal["REAL_PERSON", "VIRTUAL_CHARACTER", "SOURCE_MEDIA", "VOICE"]
CommercialScope = Literal["RESEARCH_ONLY", "COMMERCIAL"]
RightsStatus = Literal["ACTIVE", "REVOKED"]
ScopeValue = Annotated[
    str,
    Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$"),
]


class RightsReleaseCreate(BaseModel):
    subject_type: SubjectType
    subject_id: str = Field(min_length=1, max_length=128)
    allowed_operations: frozenset[ScopeValue] = Field(min_length=1)
    allowed_markets: frozenset[ScopeValue] = Field(min_length=1)
    allowed_languages: frozenset[ScopeValue] = Field(min_length=1)
    commercial_scope: CommercialScope
    valid_from: datetime
    expires_at: datetime | None = None
    minor_guardian_consent: bool = False
    source_asset_ids: tuple[UUID, ...] = ()
    evidence_uri: str = Field(min_length=1)
    evidence_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    supersedes_release_id: UUID | None = None
    created_by: UUID

    @field_validator("valid_from", "expires_at")
    @classmethod
    def require_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("rights timestamps must include a timezone")
        return value

    @model_validator(mode="after")
    def validate_window_and_scope(self) -> RightsReleaseCreate:
        if self.expires_at is not None and self.expires_at <= self.valid_from:
            raise ValueError("rights expiry must be after valid_from")
        if len(self.source_asset_ids) != len(set(self.source_asset_ids)):
            raise ValueError("rights source asset IDs must be unique")
        parsed = urlparse(self.evidence_uri)
        if parsed.scheme not in {"s3", "https"}:
            raise ValueError("rights evidence URI must use S3 or HTTPS")
        return self


class RightsRevoke(BaseModel):
    expected_state_version: int = Field(ge=1)
    actor_id: UUID
    reason: str = Field(min_length=1, max_length=1000)


class RightsExecutionCheck(BaseModel):
    operation: ScopeValue
    market: ScopeValue
    language: ScopeValue
    commercial_use: bool = True
    at: datetime | None = None

    @field_validator("at")
    @classmethod
    def require_check_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("execution check timestamp must include a timezone")
        return value


class RightsExecutionDecision(BaseModel):
    allowed: bool
    reason_codes: tuple[str, ...]
    rights_release_id: UUID
    state_version: int
    evaluated_at: datetime


class RightsReleaseRead(BaseModel):
    id: UUID
    project_id: UUID
    subject_type: SubjectType
    subject_id: str
    version: int
    status: RightsStatus
    state_version: int
    allowed_operations: frozenset[str]
    allowed_markets: frozenset[str]
    allowed_languages: frozenset[str]
    commercial_scope: CommercialScope
    valid_from: datetime
    expires_at: datetime | None = None
    revoked_at: datetime | None = None
    revoked_by: UUID | None = None
    revocation_reason: str | None = None
    minor_guardian_consent: bool
    source_asset_ids: tuple[UUID, ...]
    evidence_uri: str
    evidence_sha256: str
    supersedes_release_id: UUID | None = None
    created_by: UUID
    created_at: datetime
    updated_at: datetime
