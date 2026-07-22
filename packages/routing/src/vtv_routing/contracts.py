from __future__ import annotations

from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True)


class VisualRoute(StrEnum):
    PRESERVE = "A"
    SUBTITLE_CLEAN = "B"
    CHARACTER_REPLACE = "C"
    BACKGROUND_REPLACE = "D"
    JOINT_REPLACE = "E"
    FULL_REGEN = "F"


class ShotVisualFeatures(FrozenModel):
    shot_id: UUID
    shot_no: int = Field(ge=1)
    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)
    duration_ms: int = Field(gt=0)
    person_count: int = Field(ge=0)
    has_face_visible: bool
    max_face_scale: float = Field(ge=0, le=1)
    max_occlusion: float = Field(ge=0, le=1)
    has_text_overlay: bool
    has_dialogue: bool
    dialogue_duration_seconds: float = Field(ge=0)
    has_background_replacement_needed: bool = False
    full_regen_required: bool = False
    primary_scene_label: str = ""

    @model_validator(mode="after")
    def validate_interval(self) -> ShotVisualFeatures:
        if self.end_ms <= self.start_ms:
            raise ValueError("end_ms must be greater than start_ms")
        return self


class ShotWorkflowDecision(FrozenModel):
    shot_id: UUID
    shot_no: int = Field(ge=1)
    route: VisualRoute
    reason_codes: tuple[str, ...] = Field(min_length=1)
    candidate_count: int = Field(ge=1, le=6)
    cost_tier: Literal["FREE", "LOW", "MEDIUM", "HIGH", "VERY_HIGH"]
    router_release: str = Field(min_length=1)


class EpisodeWorkflowPlan(FrozenModel):
    schema_version: Literal["vtv.workflow-plan.v1"] = "vtv.workflow-plan.v1"
    episode_id: UUID
    total_shots: int = Field(ge=1)
    decisions: tuple[ShotWorkflowDecision, ...]
    route_distribution: dict[str, int]
    estimated_cost_tier: str
    router_release: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_decisions(self) -> EpisodeWorkflowPlan:
        if len(self.decisions) != self.total_shots:
            raise ValueError("decisions must cover all shots")
        if [d.shot_no for d in self.decisions] != list(range(1, self.total_shots + 1)):
            raise ValueError("shot numbers must be contiguous from one")
        return self
