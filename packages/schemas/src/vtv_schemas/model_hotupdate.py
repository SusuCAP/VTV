from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class ModelHotUpdateConfig(BaseModel):
    """Configuration for model hot-update without service restart.

    When a new model_release_id is set as ACTIVE, the orchestrator will:
    1. Complete in-flight stages with the old model
    2. Use the new model for all newly claimed stages
    3. Record the changeover event in Outbox
    """

    model_key: str = Field(min_length=1, max_length=64)
    changeover_strategy: Literal["drain_then_switch", "immediate"] = "drain_then_switch"
    max_drain_seconds: int = Field(default=300, ge=0, le=3600)
    # drain_then_switch: wait for in-flight to complete (up to max_drain_seconds)
    # immediate: use new model for next claim (in-flight complete with old model)
    rollback_on_failure_rate: float = Field(default=0.5, ge=0, le=1)
    # If failure rate exceeds this within first 20 stages after switch → auto-rollback


class ModelChangeover(BaseModel):
    """Record of a model hot-update event."""

    model_key: str
    previous_release_id: UUID | None
    new_release_id: UUID
    strategy: str
    triggered_by: str = Field(min_length=1, max_length=200)
    started_at: datetime
    completed_at: datetime | None = None
    stages_completed_with_new: int = Field(default=0, ge=0)
    rolled_back: bool = False
    rollback_reason: str | None = None
