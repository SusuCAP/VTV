from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

ArtifactStatus = Literal["DRAFT", "CONFIRMED", "RELEASED", "STALE"]


class ArtifactReleaseCreate(BaseModel):
    artifact_type: str = Field(min_length=1, max_length=64, pattern=r"^[A-Z][A-Z0-9_]*$")
    content_asset_id: UUID
    supersedes_release_id: UUID | None = None
    dependency_release_ids: tuple[UUID, ...] = ()


class ArtifactTransition(BaseModel):
    expected_state_version: int = Field(ge=1)


class ArtifactConfirm(ArtifactTransition):
    actor_id: UUID


class ArtifactReleaseRead(BaseModel):
    id: UUID
    project_id: UUID
    artifact_type: str
    version: int
    status: ArtifactStatus
    state_version: int
    content_asset_id: UUID
    supersedes_release_id: UUID | None = None
    dependency_release_ids: tuple[UUID, ...] = ()
    confirmed_by: UUID | None = None
    confirmed_at: datetime | None = None
    released_at: datetime | None = None
    stale_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
