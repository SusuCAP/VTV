from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True)


class ReviewState(StrEnum):
    MACHINE_DRAFT = "MACHINE_DRAFT"
    HUMAN_APPROVED = "HUMAN_APPROVED"


class Utterance(FrozenModel):
    utterance_id: str = Field(min_length=1, max_length=128)
    character_id: str = Field(min_length=1, max_length=128)
    source_text: str = Field(min_length=1)
    source_language: str = Field(min_length=2, max_length=35)
    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(gt=0)
    emotion: str = Field(default="neutral", min_length=1, max_length=64)
    protected_terms: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_interval(self) -> Utterance:
        if self.end_seconds <= self.start_seconds:
            raise ValueError("utterance end must be after start")
        return self

    @property
    def duration_seconds(self) -> float:
        return self.end_seconds - self.start_seconds


class LocalizedUtterance(FrozenModel):
    utterance: Utterance
    target_text: str = Field(min_length=1)
    target_language: str = Field(min_length=2, max_length=35)
    target_market: str = Field(min_length=2, max_length=35)
    localization_release: str = Field(min_length=1, max_length=256)
    review_state: ReviewState = ReviewState.MACHINE_DRAFT
    semantic_entity_ids: tuple[str, ...] = ()


class TranslationAdapter(Protocol):
    @property
    def model_release(self) -> str: ...

    def localize(
        self,
        utterances: tuple[Utterance, ...],
        *,
        target_language: str,
        target_market: str,
        localization_release: str,
    ) -> tuple[LocalizedUtterance, ...]: ...


class VoiceRightsSnapshot(FrozenModel):
    rights_release_id: UUID
    state_version: int = Field(ge=1)
    subject_id: str = Field(min_length=1, max_length=128)
    allowed_operations: frozenset[str] = Field(min_length=1)
    allowed_languages: frozenset[str] = Field(min_length=1)
    allowed_markets: frozenset[str] = Field(min_length=1)
    commercial_allowed: bool
    valid_at_execution: bool

    def permits(self, *, language: str, market: str, commercial: bool) -> bool:
        return self.permits_operation(
            operation="voice_clone",
            language=language,
            market=market,
            commercial=commercial,
        )

    def permits_operation(
        self, *, operation: str, language: str, market: str, commercial: bool
    ) -> bool:
        return (
            operation in self.allowed_operations
            and language in self.allowed_languages
            and market in self.allowed_markets
            and (not commercial or self.commercial_allowed)
            and self.valid_at_execution
        )


class VoiceRelease(FrozenModel):
    voice_release_id: UUID
    character_id: str = Field(min_length=1, max_length=128)
    model_release: str = Field(min_length=1, max_length=256)
    reference_asset_sha256s: tuple[str, ...] = Field(min_length=1)
    rights: VoiceRightsSnapshot

    @model_validator(mode="after")
    def validate_hashes(self) -> VoiceRelease:
        for value in self.reference_asset_sha256s:
            if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
                raise ValueError("voice reference hashes must be lowercase SHA-256")
        if self.character_id != self.rights.subject_id:
            raise ValueError("voice release subject must match character")
        return self


class TtsRequest(FrozenModel):
    localized: LocalizedUtterance
    voice_release: VoiceRelease
    seed: int = Field(ge=0, le=2**63 - 1)
    speed: float = Field(default=1, ge=0.5, le=2)
    candidate_count: int = Field(default=2, ge=1, le=4)
    commercial_use: bool = True

    @model_validator(mode="after")
    def validate_voice_and_rights(self) -> TtsRequest:
        utterance = self.localized.utterance
        if utterance.character_id != self.voice_release.character_id:
            raise ValueError("voice release does not belong to utterance character")
        if not self.voice_release.rights.permits(
            language=self.localized.target_language,
            market=self.localized.target_market,
            commercial=self.commercial_use,
        ):
            raise ValueError("voice rights do not permit this TTS request")
        return self

    @property
    def target_duration_seconds(self) -> float:
        return self.localized.utterance.duration_seconds


class TtsCandidate(FrozenModel):
    utterance_id: str = Field(min_length=1, max_length=128)
    variant_no: int = Field(ge=1, le=4)
    audio_uri: str = Field(min_length=1)
    audio_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    duration_seconds: float = Field(gt=0)
    voice_release_id: UUID
    model_release: str = Field(min_length=1, max_length=256)
    seed: int = Field(ge=0, le=2**63 - 1)
    speed: float = Field(ge=0.5, le=2)
    emotion: str = Field(min_length=1, max_length=64)


class TtsAdapter(Protocol):
    @property
    def model_release(self) -> str: ...

    def synthesize(
        self, request: TtsRequest, output_directory: Path
    ) -> tuple[TtsCandidate, ...]: ...


class LipSyncLevel(StrEnum):
    L0_NONE = "L0_NONE"
    L1_FAST = "L1_FAST"
    L2_PRESERVE_SOURCE = "L2_PRESERVE_SOURCE"
    L3_GENERATIVE_FACE = "L3_GENERATIVE_FACE"
    L4_FULL_BODY = "L4_FULL_BODY"
    L5_FULL_REGEN = "L5_FULL_REGEN"


class ShotDialogueFeatures(FrozenModel):
    shot_id: UUID
    mouth_visible: bool
    face_scale: float = Field(ge=0, le=1)
    occlusion: float = Field(ge=0, le=1)
    body_visible: bool
    dialogue_duration_seconds: float = Field(gt=0)
    original_performance_reusable: bool = True
    full_regeneration_required: bool = False


class LipSyncDecision(FrozenModel):
    shot_id: UUID
    level: LipSyncLevel
    reason_codes: tuple[str, ...] = Field(min_length=1)
    maximum_duration_deviation: float = Field(gt=0, le=0.08)


class LipSyncRouter(Protocol):
    @property
    def router_release(self) -> str: ...

    def route(self, features: ShotDialogueFeatures) -> LipSyncDecision: ...


class LipSyncRequest(FrozenModel):
    features: ShotDialogueFeatures
    decision: LipSyncDecision
    source_video_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    source_video_duration_seconds: float = Field(gt=0)
    adopted_tts_variant_id: UUID
    audio_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    target_language: str = Field(min_length=2, max_length=35)
    target_market: str = Field(min_length=2, max_length=35)
    rights: VoiceRightsSnapshot
    seed: int = Field(ge=0, le=2**63 - 1)
    candidate_count: int = Field(default=2, ge=1, le=6)
    commercial_use: bool = True

    @model_validator(mode="after")
    def validate_route_and_rights(self) -> LipSyncRequest:
        if self.features.shot_id != self.decision.shot_id:
            raise ValueError("lipsync decision must belong to the requested shot")
        if self.decision.level is LipSyncLevel.L0_NONE and self.candidate_count != 1:
            raise ValueError("L0 passthrough must produce exactly one deterministic candidate")
        if not self.rights.permits_operation(
            operation="lipsync",
            language=self.target_language,
            market=self.target_market,
            commercial=self.commercial_use,
        ):
            raise ValueError("voice rights do not permit this lipsync request")
        return self


class LipSyncCandidate(FrozenModel):
    shot_id: UUID
    variant_no: int = Field(ge=1, le=6)
    video_uri: str = Field(min_length=1)
    video_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    duration_seconds: float = Field(gt=0)
    model_release: str = Field(min_length=1, max_length=256)
    seed: int = Field(ge=0, le=2**63 - 1)
    level: LipSyncLevel


class LipSyncAdapter(Protocol):
    @property
    def model_release(self) -> str: ...

    def render(
        self,
        request: LipSyncRequest,
        source_video: Path,
        audio: Path,
        output_directory: Path,
    ) -> tuple[LipSyncCandidate, ...]: ...
