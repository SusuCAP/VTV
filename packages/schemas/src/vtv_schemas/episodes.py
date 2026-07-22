from uuid import UUID

from pydantic import BaseModel, Field


class EpisodeRead(BaseModel):
    id: UUID
    project_id: UUID
    episode_no: int = Field(ge=1)
    title: str | None = None
    duration_ms: int | None = Field(default=None, ge=0)
    upload_status: str = "COMPLETED"
    processing_status: str = "QUEUED"
    source_asset_id: UUID | None = None
