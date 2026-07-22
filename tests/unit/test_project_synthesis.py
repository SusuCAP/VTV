import pytest
from pydantic import ValidationError
from vtv_analysis import (
    AudioAnalysis,
    CharacterProfile,
    DeterministicProjectSynthesizer,
    GeometryObservation,
    LocalizationBible,
    NormalizedBox,
    PersonObservation,
    SceneObservation,
    VisionAnalysis,
)


def test_project_synthesizer_builds_version_linked_drafts() -> None:
    audio = AudioAnalysis(
        duration_seconds=2,
        language="zh-CN",
        speech=(),
        transcript=(),
        speakers=(),
    )
    vision = VisionAnalysis(
        duration_seconds=2,
        people=(
            PersonObservation(
                observation_id="p1",
                track_id="track-a",
                start_seconds=0,
                end_seconds=2,
                box=NormalizedBox(x=0.2, y=0.1, width=0.5, height=0.8),
                face_visible=True,
                confidence=0.9,
            ),
        ),
        scenes=(
            SceneObservation(
                scene_id="scene-a",
                start_seconds=0,
                end_seconds=2,
                labels=("home",),
                confidence=0.9,
            ),
        ),
        ocr=(),
        geometry=(
            GeometryObservation(
                start_seconds=0,
                end_seconds=2,
                subject_boxes=(),
                camera_motion="static",
            ),
        ),
    )

    result = DeterministicProjectSynthesizer().synthesize(
        "project-1", "episode-1", "zh-CN", "en-US", audio, vision
    )

    assert result.bible.status == "DRAFT"
    assert result.anchor_pack.bible_version == result.bible.version
    assert result.anchor_pack.anchors[0].asset_uri.startswith("pending://")
    assert result.continuity[0].characters[0].character_id == "character-001"


def test_bible_rejects_duplicate_character_ids() -> None:
    character = CharacterProfile(
        character_id="duplicate", source_track_ids=("track",), localized_name="角色"
    )
    with pytest.raises(ValidationError, match="character IDs must be unique"):
        LocalizationBible(
            bible_id="bible",
            version=1,
            status="DRAFT",
            source_locale="zh-CN",
            target_locale="en-US",
            characters=(character, character),
            locations=(),
        )
