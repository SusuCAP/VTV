import pytest
from pydantic import ValidationError
from vtv_analysis import (
    DeterministicGeometryAdapter,
    DeterministicOcrAdapter,
    DeterministicPersonAdapter,
    DeterministicSceneAdapter,
    NormalizedBox,
    ShotSpan,
    VisionAnalysisPipeline,
)


def test_vision_pipeline_preserves_shot_time_and_spatial_contracts() -> None:
    pipeline = VisionAnalysisPipeline(
        people=DeterministicPersonAdapter(),
        scenes=DeterministicSceneAdapter(),
        ocr=DeterministicOcrAdapter(),
        geometry=DeterministicGeometryAdapter(),
    )
    shots = (
        ShotSpan(shot_no=1, start_seconds=0, end_seconds=1),
        ShotSpan(shot_no=2, start_seconds=1, end_seconds=2),
    )

    result = pipeline.analyze("file:///proxy.mp4", 2, shots)

    assert len(result.people) == 2
    assert result.people[0].track_id == "track-001"
    assert result.scenes[1].scene_id == "scene-0002"
    assert result.ocr == ()
    assert result.geometry[0].subject_boxes[0].width == 0.5


def test_normalized_box_rejects_frame_overflow() -> None:
    with pytest.raises(ValidationError, match="exceeds frame bounds"):
        NormalizedBox(x=0.8, y=0.1, width=0.3, height=0.5)


def test_vision_pipeline_rejects_observation_after_duration() -> None:
    pipeline = VisionAnalysisPipeline(
        people=DeterministicPersonAdapter(),
        scenes=DeterministicSceneAdapter(),
        ocr=DeterministicOcrAdapter(),
        geometry=DeterministicGeometryAdapter(),
    )
    shots = (ShotSpan(shot_no=1, start_seconds=0, end_seconds=2),)

    with pytest.raises(ValidationError, match="exceeds media duration"):
        pipeline.analyze("file:///proxy.mp4", 1, shots)
