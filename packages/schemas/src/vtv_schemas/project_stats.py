from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field

from .jobs import JobSummary


class ProjectStats(BaseModel):
    project_id: UUID
    episodes: int = Field(ge=0)
    total_shots: int = Field(ge=0)
    total_stage_runs: int = Field(ge=0)
    completed_stage_runs: int = Field(ge=0)
    failed_stage_runs: int = Field(ge=0)
    total_deliveries: int = Field(ge=0)
    approved_deliveries: int = Field(ge=0)
    total_cost_usd: Decimal = Field(ge=0, decimal_places=6)
    analysis_complete_episodes: int = Field(ge=0)
    production_complete_episodes: int = Field(ge=0)
    generated_at: datetime


class EpisodeJobSummary(BaseModel):
    episode_id: UUID
    jobs: list[JobSummary]
    pending_count: int = Field(ge=0)
    running_count: int = Field(ge=0)
    completed_count: int = Field(ge=0)
    failed_count: int = Field(ge=0)


class QualitySnapshot(BaseModel):
    project_id: UUID
    total_candidates_generated: int = Field(ge=0)
    qc_passed: int = Field(ge=0)
    qc_failed: int = Field(ge=0)
    qc_review: int = Field(ge=0)
    adopted_count: int = Field(ge=0)
    pass_rate: float = Field(ge=0, le=1)
    circuit_breaker_active: bool = False
    top_failure_reasons: list[str] = Field(default_factory=list)
    generated_at: datetime
