from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class HealthCheckResult(BaseModel):
    status: Literal["ok", "warn", "error"]
    message: str = ""
    latency_ms: float | None = None


class HealthReport(BaseModel):
    status: Literal["ok", "degraded", "error"]
    version: str = "0.1.0"
    checks: dict[str, HealthCheckResult]
    timestamp: datetime


class SystemMetrics(BaseModel):
    active_projects: int = Field(ge=0)
    archived_projects: int = Field(ge=0)
    total_episodes: int = Field(ge=0)
    total_stage_runs: int = Field(ge=0)
    pending_stage_runs: int = Field(ge=0)
    running_stage_runs: int = Field(ge=0)
    failed_stage_runs: int = Field(ge=0)
    total_deliveries: int = Field(ge=0)
    approved_deliveries: int = Field(ge=0)
    orphan_asset_count: int = Field(ge=0)
    generated_at: datetime
