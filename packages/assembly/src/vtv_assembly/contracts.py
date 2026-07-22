from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True)


class SubtitleCue(FrozenModel):
    index: int = Field(ge=1)
    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(gt=0)
    text: str = Field(min_length=1)
    speaker_id: str | None = Field(default=None, max_length=128)

    @model_validator(mode="after")
    def valid_interval(self) -> SubtitleCue:
        if self.end_seconds <= self.start_seconds:
            raise ValueError("subtitle cue end must be after start")
        if "\x00" in self.text:
            raise ValueError("subtitle cue cannot contain NUL")
        return self


class SubtitleDocument(FrozenModel):
    locale: str = Field(min_length=2, max_length=35)
    cues: tuple[SubtitleCue, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def ordered_non_overlapping_cues(self) -> SubtitleDocument:
        if [item.index for item in self.cues] != list(range(1, len(self.cues) + 1)):
            raise ValueError("subtitle cue indices must be contiguous from one")
        for previous, current in zip(self.cues, self.cues[1:], strict=False):
            if current.start_seconds < previous.end_seconds:
                raise ValueError("subtitle cues must be ordered and non-overlapping")
        return self


class MixRole(StrEnum):
    DIALOGUE = "DIALOGUE"
    MUSIC = "MUSIC"
    EFFECTS = "EFFECTS"
    BACKGROUND = "BACKGROUND"


class AudioMixTrack(FrozenModel):
    asset_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    role: MixRole
    start_seconds: float = Field(default=0, ge=0)
    gain_db: float = Field(default=0, ge=-60, le=12)
    room_reverb: float = Field(default=0, ge=0, le=1)

    @model_validator(mode="after")
    def stem_starts_at_zero(self) -> AudioMixTrack:
        if self.role is not MixRole.DIALOGUE and self.start_seconds != 0:
            raise ValueError("full-length stems must start at zero")
        if self.role is not MixRole.DIALOGUE and self.room_reverb != 0:
            raise ValueError("room reverb is only valid for dialogue tracks")
        return self


class LoudnessPreset(FrozenModel):
    name: str = Field(min_length=1, max_length=64)
    integrated_lufs: float = Field(default=-16, ge=-24, le=-14)
    true_peak_dbfs: float = Field(default=-1.5, ge=-3, le=-1)
    loudness_range_lu: float = Field(default=11, ge=1, le=20)


class AudioMixRequest(FrozenModel):
    duration_seconds: float = Field(gt=0)
    tracks: tuple[AudioMixTrack, ...] = Field(min_length=1)
    preset: LoudnessPreset = Field(
        default_factory=lambda: LoudnessPreset(name="web-dialogue")
    )
    sample_rate: int = Field(default=48_000, ge=8_000, le=192_000)
    channels: int = Field(default=2, ge=1, le=8)

    @model_validator(mode="after")
    def unique_assets_and_required_bed(self) -> AudioMixRequest:
        hashes = [item.asset_sha256 for item in self.tracks]
        if len(hashes) != len(set(hashes)):
            raise ValueError("audio mix assets must be unique")
        if not any(item.role is MixRole.DIALOGUE for item in self.tracks):
            raise ValueError("audio mix requires at least one adopted dialogue track")
        return self


class EpisodeAssemblyRequest(FrozenModel):
    duration_seconds: float = Field(gt=0)
    width: int = Field(ge=320, le=7680)
    height: int = Field(ge=320, le=7680)
    fps: float = Field(gt=0, le=120)
    video_codec: str = Field(pattern=r"^(h264|h265|av1)$")
    audio_codec: str = Field(pattern=r"^(aac|opus)$")
    burn_subtitles: bool = False
    source_video_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    mixed_audio_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    subtitle_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    subtitle_document: SubtitleDocument | None = None

    @model_validator(mode="after")
    def subtitle_required_when_burning(self) -> EpisodeAssemblyRequest:
        if self.burn_subtitles and (
            self.subtitle_sha256 is None or self.subtitle_document is None
        ):
            raise ValueError("burned subtitles require an asset and immutable document")
        if self.subtitle_document and any(
            cue.end_seconds > self.duration_seconds + 0.05
            for cue in self.subtitle_document.cues
        ):
            raise ValueError("subtitle cue exceeds episode duration")
        return self
