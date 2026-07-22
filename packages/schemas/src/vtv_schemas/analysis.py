from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel


class AnalysisDocumentRead(BaseModel):
    id: UUID
    project_id: UUID
    episode_id: UUID | None = None
    source_stage_run_id: UUID
    media_asset_id: UUID
    document_type: str
    schema_version: int
    payload: dict[str, Any]
    created_at: datetime
    updated_at: datetime
