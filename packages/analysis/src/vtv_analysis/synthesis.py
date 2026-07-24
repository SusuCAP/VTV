from dataclasses import dataclass
from hashlib import sha256
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .contracts import AudioAnalysis
from .vision import VisionAnalysis


class SynthesisEvidence(BaseModel):
    model_config = ConfigDict(frozen=True)

    episode_id: str = Field(min_length=1)
    source_type: Literal["TRANSCRIPT", "PERSON_TRACK", "SCENE", "OCR", "GEOMETRY"]
    source_id: str = Field(min_length=1)
    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(gt=0)
    excerpt: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def validate_span(self) -> "SynthesisEvidence":
        if self.end_seconds <= self.start_seconds:
            raise ValueError("evidence end_seconds must be after start_seconds")
        return self


class CharacterProfile(BaseModel):
    model_config = ConfigDict(frozen=True)

    character_id: str = Field(min_length=1)
    source_track_ids: tuple[str, ...] = Field(min_length=1)
    localized_name: str = Field(min_length=1)
    voice_profile_id: str | None = None
    visual_constraints: tuple[str, ...] = ()
    evidence: tuple[SynthesisEvidence, ...] = ()


class LocationProfile(BaseModel):
    model_config = ConfigDict(frozen=True)

    location_id: str = Field(min_length=1)
    source_scene_ids: tuple[str, ...] = Field(min_length=1)
    localized_name: str = Field(min_length=1)
    visual_constraints: tuple[str, ...] = ()
    evidence: tuple[SynthesisEvidence, ...] = ()


class GlossaryEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    source: str = Field(min_length=1)
    target: str = Field(min_length=1)
    note: str | None = None
    evidence: tuple[SynthesisEvidence, ...] = ()


class LocalizationBible(BaseModel):
    model_config = ConfigDict(frozen=True)

    bible_id: str = Field(min_length=1)
    version: int = Field(ge=1)
    status: Literal["DRAFT", "CONFIRMED", "RELEASED"]
    source_locale: str = Field(min_length=2)
    target_locale: str = Field(min_length=2)
    characters: tuple[CharacterProfile, ...]
    locations: tuple[LocationProfile, ...]
    glossary: tuple[GlossaryEntry, ...] = ()
    style_rules: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_unique_ids(self) -> "LocalizationBible":
        character_ids = [item.character_id for item in self.characters]
        location_ids = [item.location_id for item in self.locations]
        if len(character_ids) != len(set(character_ids)):
            raise ValueError("character IDs must be unique")
        if len(location_ids) != len(set(location_ids)):
            raise ValueError("location IDs must be unique")
        return self


class Anchor(BaseModel):
    model_config = ConfigDict(frozen=True)

    anchor_id: str = Field(min_length=1)
    kind: Literal["CHARACTER", "OUTFIT", "LOCATION", "VOICE"]
    subject_id: str = Field(min_length=1)
    asset_uri: str = Field(min_length=1)
    asset_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class AnchorPack(BaseModel):
    model_config = ConfigDict(frozen=True)

    pack_id: str = Field(min_length=1)
    version: int = Field(ge=1)
    status: Literal["DRAFT", "CONFIRMED", "RELEASED"]
    bible_id: str = Field(min_length=1)
    bible_version: int = Field(ge=1)
    anchors: tuple[Anchor, ...]


class CharacterContinuity(BaseModel):
    model_config = ConfigDict(frozen=True)

    character_id: str = Field(min_length=1)
    outfit_id: str | None = None
    emotional_state: str | None = None
    props: tuple[str, ...] = ()


class ContinuitySnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    snapshot_id: str = Field(min_length=1)
    episode_id: str = Field(min_length=1)
    shot_no: int = Field(ge=1)
    bible_id: str = Field(min_length=1)
    bible_version: int = Field(ge=1)
    location_id: str | None = None
    time_of_day: str | None = None
    characters: tuple[CharacterContinuity, ...] = ()
    evidence: tuple[SynthesisEvidence, ...] = ()


class ProjectSynthesis(BaseModel):
    model_config = ConfigDict(frozen=True)

    bible: LocalizationBible
    anchor_pack: AnchorPack
    continuity: tuple[ContinuitySnapshot, ...]


class ProjectSynthesisAdapter(Protocol):
    @property
    def model_release(self) -> str: ...

    def synthesize_series(
        self,
        project_id: str,
        source_locale: str,
        target_locale: str,
        episodes: tuple[tuple[str, AudioAnalysis, VisionAnalysis], ...],
        bible_version: int = 1,
        anchor_pack_version: int = 1,
    ) -> ProjectSynthesis: ...


@dataclass(frozen=True, slots=True)
class DeterministicProjectSynthesizer:
    model_release: str = "deterministic-project-synthesis@1"

    def synthesize(
        self,
        project_id: str,
        episode_id: str,
        source_locale: str,
        target_locale: str,
        audio: AudioAnalysis,
        vision: VisionAnalysis,
    ) -> ProjectSynthesis:
        return self.synthesize_series(
            project_id,
            source_locale,
            target_locale,
            ((episode_id, audio, vision),),
        )

    def synthesize_series(
        self,
        project_id: str,
        source_locale: str,
        target_locale: str,
        episodes: tuple[tuple[str, AudioAnalysis, VisionAnalysis], ...],
        bible_version: int = 1,
        anchor_pack_version: int = 1,
    ) -> ProjectSynthesis:
        if not episodes:
            raise ValueError("project synthesis requires at least one episode analysis")
        tracks = sorted(
            {person.track_id for _, _, vision in episodes for person in vision.people}
        )
        scenes = sorted(
            {scene.scene_id for _, _, vision in episodes for scene in vision.scenes}
        )
        bible_id = f"bible-{project_id}"
        bible = LocalizationBible(
            bible_id=bible_id,
            version=bible_version,
            status="DRAFT",
            source_locale=source_locale,
            target_locale=target_locale,
            characters=tuple(
                CharacterProfile(
                    character_id=f"character-{index:03d}",
                    source_track_ids=(track,),
                    localized_name=f"角色{index}",
                )
                for index, track in enumerate(tracks, 1)
            ),
            locations=tuple(
                LocationProfile(
                    location_id=f"location-{index:03d}",
                    source_scene_ids=(scene,),
                    localized_name=f"场景{index}",
                )
                for index, scene in enumerate(scenes, 1)
            ),
        )
        anchors = tuple(
            Anchor(
                anchor_id=f"anchor-{character.character_id}",
                kind="CHARACTER",
                subject_id=character.character_id,
                asset_uri=f"pending://{character.character_id}",
                asset_sha256=sha256(character.character_id.encode()).hexdigest(),
            )
            for character in bible.characters
        )
        anchor_pack = AnchorPack(
            pack_id=f"anchors-{project_id}",
            version=anchor_pack_version,
            status="DRAFT",
            bible_id=bible_id,
            bible_version=bible_version,
            anchors=anchors,
        )
        continuity = tuple(
            snapshot
            for episode_id, _audio, vision in episodes
            for snapshot in (
                ContinuitySnapshot(
                    snapshot_id=f"continuity-{episode_id}-{index}",
                    episode_id=episode_id,
                    shot_no=index,
                    bible_id=bible_id,
                    bible_version=bible_version,
                    location_id=(bible.locations[0].location_id if bible.locations else None),
                    characters=tuple(
                        CharacterContinuity(character_id=character.character_id)
                        for character in bible.characters
                    ),
                )
                for index in range(1, len(vision.geometry) + 1)
            )
        )
        return ProjectSynthesis(bible=bible, anchor_pack=anchor_pack, continuity=continuity)
