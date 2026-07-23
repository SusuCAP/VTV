from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class AlertSeverity(str):
    INFO = "INFO"
    WARN = "WARN"
    CRITICAL = "CRITICAL"


class ProductionAlert(BaseModel):
    alert_id: str = Field(min_length=1, max_length=128)
    project_id: UUID
    episode_id: UUID | None = None
    severity: Literal["INFO", "WARN", "CRITICAL"]
    alert_type: Literal[
        "circuit_breaker_tripped",
        "budget_warning",
        "budget_exceeded",
        "high_failure_rate",
        "stage_lease_expired",
        "model_rollback_triggered",
        "delivery_approved",
        "delivery_revoked",
    ]
    message: str = Field(min_length=1, max_length=1000)
    metadata: dict = Field(default_factory=dict)
    created_at: datetime
    acknowledged: bool = False
    acknowledged_by: str | None = None
    acknowledged_at: datetime | None = None


class AlertFilter(BaseModel):
    severity: Literal["INFO", "WARN", "CRITICAL"] | None = None
    alert_type: str | None = None
    acknowledged: bool | None = None
    limit: int = Field(default=50, ge=1, le=500)
    offset: int = Field(default=0, ge=0)
