from dataclasses import dataclass
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .contracts import TimedSpan


class NormalizedBox(BaseModel):
    model_config = ConfigDict(frozen=True)

    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    width: float = Field(gt=0, le=1)
    height: float = Field(gt=0, le=1)

    @model_validator(mode="after")
    def validate_bounds(self) -> "NormalizedBox":
        if self.x + self.width > 1 or self.y + self.height > 1:
            raise ValueError("normalized box exceeds frame bounds")
        return self


class ShotSpan(TimedSpan):
    shot_no: int = Field(ge=1)


class PersonObservation(TimedSpan):
    observation_id: str = Field(min_length=1)
    track_id: str = Field(min_length=1)
    box: NormalizedBox
    face_visible: bool
    confidence: float = Field(ge=0, le=1)
    embedding_ref: str | None = None


class SceneObservation(TimedSpan):
    scene_id: str = Field(min_length=1)
    labels: tuple[str, ...]
    confidence: float = Field(ge=0, le=1)


class OcrObservation(TimedSpan):
    text: str = Field(min_length=1)
    box: NormalizedBox
    confidence: float = Field(ge=0, le=1)
    script: str | None = None


class GeometryObservation(TimedSpan):
    subject_boxes: tuple[NormalizedBox, ...]
    protected_regions: tuple[NormalizedBox, ...] = ()
    camera_motion: str = Field(pattern=r"^(static|pan|tilt|zoom|handheld|unknown)$")


class VisionAnalysis(BaseModel):
    model_config = ConfigDict(frozen=True)

    duration_seconds: float = Field(gt=0)
    people: tuple[PersonObservation, ...]
    scenes: tuple[SceneObservation, ...]
    ocr: tuple[OcrObservation, ...]
    geometry: tuple[GeometryObservation, ...]

    @model_validator(mode="after")
    def validate_bounds(self) -> "VisionAnalysis":
        spans = (*self.people, *self.scenes, *self.ocr, *self.geometry)
        if any(span.end_seconds > self.duration_seconds for span in spans):
            raise ValueError("vision observation exceeds media duration")
        return self


class PersonAdapter(Protocol):
    @property
    def model_release(self) -> str: ...

    def analyze(
        self, media_uri: str, shots: tuple[ShotSpan, ...]
    ) -> tuple[PersonObservation, ...]: ...


class SceneAdapter(Protocol):
    @property
    def model_release(self) -> str: ...

    def analyze(
        self, media_uri: str, shots: tuple[ShotSpan, ...]
    ) -> tuple[SceneObservation, ...]: ...


class OcrAdapter(Protocol):
    @property
    def model_release(self) -> str: ...

    def analyze(
        self, media_uri: str, shots: tuple[ShotSpan, ...]
    ) -> tuple[OcrObservation, ...]: ...


class GeometryAdapter(Protocol):
    @property
    def model_release(self) -> str: ...

    def analyze(
        self, media_uri: str, shots: tuple[ShotSpan, ...]
    ) -> tuple[GeometryObservation, ...]: ...


@dataclass(frozen=True, slots=True)
class DeterministicPersonAdapter:
    model_release: str = "mock-person@1"

    def analyze(
        self, media_uri: str, shots: tuple[ShotSpan, ...]
    ) -> tuple[PersonObservation, ...]:
        del media_uri
        return tuple(
            PersonObservation(
                observation_id=f"person-observation-{shot.shot_no}",
                track_id="track-001",
                start_seconds=shot.start_seconds,
                end_seconds=shot.end_seconds,
                box=NormalizedBox(x=0.25, y=0.1, width=0.5, height=0.8),
                face_visible=True,
                confidence=1,
                embedding_ref="mock://embedding/person-001",
            )
            for shot in shots
        )


@dataclass(frozen=True, slots=True)
class DeterministicSceneAdapter:
    model_release: str = "mock-scene@1"

    def analyze(
        self, media_uri: str, shots: tuple[ShotSpan, ...]
    ) -> tuple[SceneObservation, ...]:
        del media_uri
        return tuple(
            SceneObservation(
                scene_id=f"scene-{shot.shot_no:04d}",
                start_seconds=shot.start_seconds,
                end_seconds=shot.end_seconds,
                labels=("unknown-location",),
                confidence=1,
            )
            for shot in shots
        )


@dataclass(frozen=True, slots=True)
class DeterministicOcrAdapter:
    model_release: str = "mock-ocr@1"

    def analyze(self, media_uri: str, shots: tuple[ShotSpan, ...]) -> tuple[OcrObservation, ...]:
        del media_uri, shots
        return ()


@dataclass(frozen=True, slots=True)
class DeterministicGeometryAdapter:
    model_release: str = "mock-geometry@1"

    def analyze(
        self, media_uri: str, shots: tuple[ShotSpan, ...]
    ) -> tuple[GeometryObservation, ...]:
        del media_uri
        subject = NormalizedBox(x=0.25, y=0.1, width=0.5, height=0.8)
        return tuple(
            GeometryObservation(
                start_seconds=shot.start_seconds,
                end_seconds=shot.end_seconds,
                subject_boxes=(subject,),
                camera_motion="unknown",
            )
            for shot in shots
        )


@dataclass(frozen=True, slots=True)
class VisionAnalysisPipeline:
    people: PersonAdapter
    scenes: SceneAdapter
    ocr: OcrAdapter
    geometry: GeometryAdapter

    def analyze(
        self, media_uri: str, duration_seconds: float, shots: tuple[ShotSpan, ...]
    ) -> VisionAnalysis:
        return VisionAnalysis(
            duration_seconds=duration_seconds,
            people=self.people.analyze(media_uri, shots),
            scenes=self.scenes.analyze(media_uri, shots),
            ocr=self.ocr.analyze(media_uri, shots),
            geometry=self.geometry.analyze(media_uri, shots),
        )
