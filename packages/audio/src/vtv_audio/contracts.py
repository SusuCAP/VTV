from enum import StrEnum
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StemKind(StrEnum):
    DIALOGUE = "DIALOGUE"
    MUSIC = "MUSIC"
    EFFECTS = "EFFECTS"
    BACKGROUND = "BACKGROUND"


class StemOutput(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: StemKind
    path: Path
    duration_seconds: float = Field(gt=0)
    channels: int = Field(ge=1, le=16)
    sample_rate: int = Field(ge=8000, le=384000)


class StemSeparationResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    source_duration_seconds: float = Field(gt=0)
    stems: tuple[StemOutput, ...] = Field(min_length=1)
    model_release: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_stems(self) -> "StemSeparationResult":
        kinds = [stem.kind for stem in self.stems]
        if len(kinds) != len(set(kinds)):
            raise ValueError("stem kinds must be unique")
        if StemKind.DIALOGUE not in kinds:
            raise ValueError("stem separation must provide a dialogue candidate")
        if any(
            abs(stem.duration_seconds - self.source_duration_seconds) > 0.05
            for stem in self.stems
        ):
            raise ValueError("stem duration differs from source by more than 50 ms")
        return self


class StemSeparationAdapter(Protocol):
    @property
    def model_release(self) -> str: ...

    def separate(self, source: Path, output_directory: Path) -> StemSeparationResult: ...
