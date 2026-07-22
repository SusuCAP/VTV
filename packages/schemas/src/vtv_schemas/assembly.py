from __future__ import annotations

import json
from hashlib import sha256
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


class AdoptedPictureSelection(BaseModel):
    shot_id: UUID
    adopted_variant_id: UUID


class AdoptedDialogueSelection(BaseModel):
    adopted_variant_id: UUID
    gain_db: float = Field(default=0, ge=-60, le=12)
    room_reverb: float = Field(default=0, ge=0, le=1)


class StemSelection(BaseModel):
    asset_id: UUID
    role: Literal["MUSIC", "EFFECTS", "BACKGROUND"]
    gain_db: float = Field(default=-8, ge=-60, le=12)


class AssemblySubtitleCue(BaseModel):
    index: int = Field(ge=1)
    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(gt=0)
    text: str = Field(min_length=1)
    speaker_id: str | None = Field(default=None, max_length=128)


class EpisodeAssemblyJobCreate(BaseModel):
    episode_id: UUID
    source_video_asset_id: UUID
    picture_selections: tuple[AdoptedPictureSelection, ...] = ()
    dialogue_selections: tuple[AdoptedDialogueSelection, ...] = Field(min_length=1)
    stem_selections: tuple[StemSelection, ...] = ()
    subtitle_cues: tuple[AssemblySubtitleCue, ...] = Field(min_length=1)
    loudness_preset: Literal["web-dialogue", "broadcast", "mobile"] = "web-dialogue"
    burn_subtitles: bool = True

    @model_validator(mode="after")
    def unique_and_ordered_inputs(self) -> EpisodeAssemblyJobCreate:
        groups = (
            ([item.shot_id for item in self.picture_selections], "picture shots"),
            ([item.adopted_variant_id for item in self.picture_selections], "picture variants"),
            (
                [item.adopted_variant_id for item in self.dialogue_selections],
                "dialogue variants",
            ),
            ([item.asset_id for item in self.stem_selections], "stem assets"),
            ([item.role for item in self.stem_selections], "stem roles"),
        )
        for values, label in groups:
            if len(values) != len(set(values)):
                raise ValueError(f"{label} must be unique")
        if [item.index for item in self.subtitle_cues] != list(
            range(1, len(self.subtitle_cues) + 1)
        ):
            raise ValueError("subtitle cue indices must be contiguous from one")
        for previous, current in zip(
            self.subtitle_cues, self.subtitle_cues[1:], strict=False
        ):
            if current.start_seconds < previous.end_seconds:
                raise ValueError("subtitle cues must be ordered and non-overlapping")
        if any(item.end_seconds <= item.start_seconds for item in self.subtitle_cues):
            raise ValueError("subtitle cue end must be after start")
        return self

    @property
    def fingerprint(self) -> str:
        canonical = json.dumps(
            self.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return sha256(canonical.encode()).hexdigest()
