from __future__ import annotations

import json
from hashlib import sha256
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


class DubbingUtteranceCreate(BaseModel):
    utterance_id: str = Field(min_length=1, max_length=128)
    character_id: str = Field(min_length=1, max_length=128)
    source_text: str = Field(min_length=1)
    source_language: str = Field(min_length=2, max_length=35)
    target_text: str = Field(min_length=1)
    target_language: str = Field(min_length=2, max_length=35)
    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(gt=0)
    emotion: str = Field(default="neutral", min_length=1, max_length=64)
    protected_terms: tuple[str, ...] = ()
    semantic_entity_ids: tuple[str, ...] = ()
    voice_release_id: UUID
    rights_release_id: UUID
    seed: int = Field(ge=0, le=2**63 - 1)
    speed: float = Field(default=1, ge=0.5, le=2)
    candidate_count: int = Field(default=2, ge=1, le=4)
    maximum_duration_deviation: float = Field(default=0.08, gt=0, le=0.08)

    @model_validator(mode="after")
    def validate_timing(self) -> DubbingUtteranceCreate:
        if self.end_seconds <= self.start_seconds:
            raise ValueError("dubbing utterance end must be after start")
        return self


class DubbingJobCreate(BaseModel):
    episode_id: UUID
    localization_release_id: UUID
    utterances: tuple[DubbingUtteranceCreate, ...] = Field(min_length=1)
    commercial_use: bool = True

    @model_validator(mode="after")
    def unique_utterance_ids(self) -> DubbingJobCreate:
        identifiers = [item.utterance_id for item in self.utterances]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("dubbing utterance IDs must be unique")
        return self

    @property
    def fingerprint(self) -> str:
        payload = json.dumps(
            self.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return sha256(payload.encode()).hexdigest()


class LipSyncShotCreate(BaseModel):
    shot_id: UUID
    source_video_asset_id: UUID
    adopted_tts_variant_id: UUID
    mouth_visible: bool
    face_scale: float = Field(ge=0, le=1)
    occlusion: float = Field(ge=0, le=1)
    body_visible: bool
    dialogue_duration_seconds: float = Field(gt=0)
    original_performance_reusable: bool = True
    full_regeneration_required: bool = False
    seed: int = Field(ge=0, le=2**63 - 1)
    candidate_count: int = Field(default=2, ge=1, le=6)


class LipSyncJobCreate(BaseModel):
    episode_id: UUID
    shots: tuple[LipSyncShotCreate, ...] = Field(min_length=1)
    commercial_use: bool = True

    @model_validator(mode="after")
    def unique_shots(self) -> LipSyncJobCreate:
        identifiers = [item.shot_id for item in self.shots]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("lipsync shot IDs must be unique")
        return self

    @property
    def fingerprint(self) -> str:
        payload = json.dumps(
            self.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return sha256(payload.encode()).hexdigest()
