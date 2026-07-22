from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator


class TimedSpan(BaseModel):
    model_config = ConfigDict(frozen=True)

    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(gt=0)

    @model_validator(mode="after")
    def validate_interval(self) -> "TimedSpan":
        if self.end_seconds <= self.start_seconds:
            raise ValueError("end_seconds must be greater than start_seconds")
        return self


class SpeechSegment(TimedSpan):
    confidence: float = Field(ge=0, le=1)


class TranscriptWord(TimedSpan):
    text: str = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)


class TranscriptSegment(TimedSpan):
    text: str = Field(min_length=1)
    language: str = Field(min_length=2)
    words: tuple[TranscriptWord, ...] = ()


class SpeakerTurn(TimedSpan):
    speaker_id: str = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)


class AudioAnalysis(BaseModel):
    model_config = ConfigDict(frozen=True)

    duration_seconds: float = Field(gt=0)
    language: str = Field(min_length=2)
    speech: tuple[SpeechSegment, ...]
    transcript: tuple[TranscriptSegment, ...]
    speakers: tuple[SpeakerTurn, ...]

    @model_validator(mode="after")
    def validate_bounds(self) -> "AudioAnalysis":
        spans = (*self.speech, *self.transcript, *self.speakers)
        if any(span.end_seconds > self.duration_seconds for span in spans):
            raise ValueError("analysis span exceeds audio duration")
        return self


class VadAdapter(Protocol):
    @property
    def model_release(self) -> str: ...

    def detect(self, audio_uri: str, duration_seconds: float) -> tuple[SpeechSegment, ...]: ...


class AsrAdapter(Protocol):
    @property
    def model_release(self) -> str: ...

    def transcribe(
        self,
        audio_uri: str,
        speech: tuple[SpeechSegment, ...],
        language_hint: str | None,
    ) -> tuple[TranscriptSegment, ...]: ...


class DiarizationAdapter(Protocol):
    @property
    def model_release(self) -> str: ...

    def identify(
        self, audio_uri: str, speech: tuple[SpeechSegment, ...]
    ) -> tuple[SpeakerTurn, ...]: ...
