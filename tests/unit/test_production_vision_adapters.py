from pathlib import Path

import pytest
from vtv_analysis import (
    CachedVisionBackend,
    GeometryObservation,
    NormalizedBox,
    OcrObservation,
    PersonObservation,
    QwenGeometryAdapter,
    QwenOcrAdapter,
    QwenPersonAdapter,
    QwenSceneAdapter,
    SceneObservation,
    ShotSpan,
    VisionAnalysisPipeline,
    VisionBackendOutput,
)


class FakeBackend:
    def __init__(self, output: VisionBackendOutput) -> None:
        self.output = output
        self.calls = 0

    def analyze(self, media: Path, shots: tuple[ShotSpan, ...]) -> VisionBackendOutput:
        self.calls += 1
        assert media.name == "video.mp4"
        assert len(shots) == 1
        return self.output


def _output(end_seconds: float = 2) -> VisionBackendOutput:
    box = NormalizedBox(x=0.1, y=0.1, width=0.5, height=0.8)
    return VisionBackendOutput(
        people=(
            PersonObservation(
                observation_id="person-1",
                track_id="track-1",
                start_seconds=0,
                end_seconds=end_seconds,
                box=box,
                face_visible=True,
                confidence=0.9,
            ),
        ),
        scenes=(
            SceneObservation(
                scene_id="scene-1",
                start_seconds=0,
                end_seconds=end_seconds,
                labels=("office",),
                confidence=0.8,
            ),
        ),
        ocr=(
            OcrObservation(
                text="合同",
                start_seconds=0,
                end_seconds=end_seconds,
                box=box,
                confidence=0.95,
                script="Hans",
            ),
        ),
        geometry=(
            GeometryObservation(
                start_seconds=0,
                end_seconds=end_seconds,
                subject_boxes=(box,),
                camera_motion="static",
            ),
        ),
    )


def test_qwen_adapters_share_one_strongly_typed_backend_call(tmp_path: Path) -> None:
    media = tmp_path / "video.mp4"
    media.write_bytes(b"video")
    shots = (ShotSpan(shot_no=1, start_seconds=0, end_seconds=2),)
    raw = FakeBackend(_output())
    cached = CachedVisionBackend(raw)
    pipeline = VisionAnalysisPipeline(
        people=QwenPersonAdapter(cached, "qwen@1:people"),
        scenes=QwenSceneAdapter(cached, "qwen@1:scenes"),
        ocr=QwenOcrAdapter(cached, "qwen@1:ocr"),
        geometry=QwenGeometryAdapter(cached, "qwen@1:geometry"),
    )

    result = pipeline.analyze(media.resolve().as_uri(), 2, shots)

    assert raw.calls == 1
    assert result.people[0].track_id == "track-1"
    assert result.ocr[0].text == "合同"


def test_cached_backend_rejects_observation_outside_declared_shot(tmp_path: Path) -> None:
    media = tmp_path / "video.mp4"
    media.write_bytes(b"video")
    shots = (ShotSpan(shot_no=1, start_seconds=0, end_seconds=2),)

    with pytest.raises(ValueError, match="not contained"):
        CachedVisionBackend(FakeBackend(_output(2.1))).analyze(
            media.resolve().as_uri(), shots
        )


def test_production_vision_backend_requires_local_media() -> None:
    with pytest.raises(ValueError, match="requires local media"):
        CachedVisionBackend(FakeBackend(_output())).analyze(
            "s3://bucket/video.mp4",
            (ShotSpan(shot_no=1, start_seconds=0, end_seconds=2),),
        )
