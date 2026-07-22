from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field


class StageCostEntry(BaseModel):
    stage_type: str
    stage_run_count: int = Field(ge=0)
    total_cost_usd: Decimal = Field(ge=0, decimal_places=6)
    avg_cost_usd: Decimal = Field(ge=0, decimal_places=6)
    p95_latency_seconds: float = Field(ge=0)


class ModelCostEntry(BaseModel):
    model_key: str
    model_release_name: str
    invocation_count: int = Field(ge=0)
    total_cost_usd: Decimal = Field(ge=0, decimal_places=6)
    total_gpu_seconds: float = Field(ge=0)


class ProjectCostReport(BaseModel):
    project_id: UUID
    workspace_id: UUID
    report_generated_at: datetime
    period_start: datetime | None = None
    period_end: datetime | None = None
    total_cost_usd: Decimal = Field(ge=0, decimal_places=6)
    currency: str = Field(default="USD", pattern=r"^[A-Z]{3}$")
    by_stage: list[StageCostEntry] = Field(default_factory=list)
    by_model: list[ModelCostEntry] = Field(default_factory=list)
    episode_count: int = Field(ge=0)
    shot_count: int = Field(ge=0)
    cost_per_episode_usd: Decimal = Field(ge=0, decimal_places=6)
    cost_per_shot_usd: Decimal = Field(ge=0, decimal_places=6)
    budget_usd: Decimal | None = None
    budget_utilization_pct: float | None = None
