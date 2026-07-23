from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .enums import ProjectStatus


class OutputSpec(BaseModel):
    aspect_ratio: Literal["9:16", "16:9", "1:1"] = "9:16"
    width: int = Field(default=1080, ge=320, le=7680)
    height: int = Field(default=1920, ge=320, le=7680)
    fps: float = Field(default=24, gt=0, le=120)
    video_codec: Literal["h264", "h265", "av1"] = "h264"
    audio_codec: Literal["aac", "opus"] = "aac"
    subtitle_formats: list[Literal["srt", "vtt", "burned"]] = Field(
        default_factory=lambda: ["srt", "burned"]
    )


class Budget(BaseModel):
    currency: str = Field(default="USD", min_length=3, max_length=3)
    warning_at: Decimal = Field(default=Decimal("280.00"), ge=0)
    hard_limit: Decimal = Field(default=Decimal("350.00"), gt=0)

    @model_validator(mode="after")
    def warning_must_not_exceed_limit(self) -> Budget:
        if self.warning_at > self.hard_limit:
            raise ValueError("warning_at must not exceed hard_limit")
        return self


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    target_market: str = Field(min_length=2, max_length=16)
    locale: str = Field(min_length=2, max_length=35)
    timezone: str = Field(default="UTC", min_length=1, max_length=64)
    quality_profile: str = Field(default="research_best", min_length=1, max_length=64)
    output: OutputSpec = Field(default_factory=OutputSpec)
    budget: Budget = Field(default_factory=Budget)


class ProjectRead(ProjectCreate):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    workspace_id: UUID
    status: ProjectStatus
    state_version: int = Field(ge=1)
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None = None
    archive_reason: str | None = Field(default=None, max_length=500)
