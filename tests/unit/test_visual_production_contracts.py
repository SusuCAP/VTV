from __future__ import annotations

from uuid import uuid4

import pytest
from vtv_production.contracts import (
    SegmentationRequest,
    SubtitleCleanRequest,
    VisualCandidate,
    VisualGenerationRequest,
)

_GOOD_SHA = "a" * 64
_BAD_SHA = "zz" + "a" * 62  # non-hex chars


# ── VisualGenerationRequest ────────────────────────────────────────────────────


def test_visual_generation_request_valid() -> None:
    req = VisualGenerationRequest(
        shot_id=uuid4(),
        route="C",
        source_video_sha256=_GOOD_SHA,
        source_video_duration_seconds=2.0,
        seed=42,
    )
    assert req.candidate_count == 2
    assert req.target_market == "en-US"


def test_visual_generation_request_candidate_count_min() -> None:
    req = VisualGenerationRequest(
        shot_id=uuid4(),
        route="C",
        source_video_sha256=_GOOD_SHA,
        source_video_duration_seconds=1.0,
        seed=0,
        candidate_count=1,
    )
    assert req.candidate_count == 1


def test_visual_generation_request_candidate_count_max() -> None:
    req = VisualGenerationRequest(
        shot_id=uuid4(),
        route="F",
        source_video_sha256=_GOOD_SHA,
        source_video_duration_seconds=1.0,
        seed=0,
        candidate_count=6,
    )
    assert req.candidate_count == 6


def test_visual_generation_request_candidate_count_too_low() -> None:
    with pytest.raises(ValueError):
        VisualGenerationRequest(
            shot_id=uuid4(),
            route="C",
            source_video_sha256=_GOOD_SHA,
            source_video_duration_seconds=1.0,
            seed=0,
            candidate_count=0,
        )


def test_visual_generation_request_candidate_count_too_high() -> None:
    with pytest.raises(ValueError):
        VisualGenerationRequest(
            shot_id=uuid4(),
            route="C",
            source_video_sha256=_GOOD_SHA,
            source_video_duration_seconds=1.0,
            seed=0,
            candidate_count=7,
        )


def test_visual_generation_request_bad_sha256() -> None:
    with pytest.raises(ValueError):
        VisualGenerationRequest(
            shot_id=uuid4(),
            route="C",
            source_video_sha256=_BAD_SHA,
            source_video_duration_seconds=1.0,
            seed=0,
        )


# ── VisualCandidate ────────────────────────────────────────────────────────────


def test_visual_candidate_variant_no_min() -> None:
    c = VisualCandidate(
        shot_id=uuid4(),
        variant_no=1,
        video_uri="file:///tmp/v.mp4",
        video_sha256=_GOOD_SHA,
        duration_seconds=1.0,
        model_release="test@1",
        seed=0,
        route="C",
    )
    assert c.variant_no == 1


def test_visual_candidate_variant_no_max() -> None:
    c = VisualCandidate(
        shot_id=uuid4(),
        variant_no=6,
        video_uri="file:///tmp/v.mp4",
        video_sha256=_GOOD_SHA,
        duration_seconds=1.0,
        model_release="test@1",
        seed=0,
        route="F",
    )
    assert c.variant_no == 6


def test_visual_candidate_variant_no_zero_invalid() -> None:
    with pytest.raises(ValueError):
        VisualCandidate(
            shot_id=uuid4(),
            variant_no=0,
            video_uri="file:///tmp/v.mp4",
            video_sha256=_GOOD_SHA,
            duration_seconds=1.0,
            model_release="test@1",
            seed=0,
            route="C",
        )


def test_visual_candidate_variant_no_seven_invalid() -> None:
    with pytest.raises(ValueError):
        VisualCandidate(
            shot_id=uuid4(),
            variant_no=7,
            video_uri="file:///tmp/v.mp4",
            video_sha256=_GOOD_SHA,
            duration_seconds=1.0,
            model_release="test@1",
            seed=0,
            route="C",
        )


# ── SegmentationRequest ────────────────────────────────────────────────────────


def test_segmentation_request_defaults() -> None:
    req = SegmentationRequest(shot_id=uuid4(), source_video_sha256=_GOOD_SHA)
    assert req.prompt_type == "text"
    assert req.output_type == "alpha_matte"
    assert req.prompt == "person"


def test_segmentation_request_mask_video_output() -> None:
    req = SegmentationRequest(
        shot_id=uuid4(),
        source_video_sha256=_GOOD_SHA,
        output_type="mask_video",
    )
    assert req.output_type == "mask_video"


def test_segmentation_request_bad_sha256() -> None:
    with pytest.raises(ValueError):
        SegmentationRequest(shot_id=uuid4(), source_video_sha256=_BAD_SHA)


# ── SubtitleCleanRequest ───────────────────────────────────────────────────────


def test_subtitle_clean_request_valid() -> None:
    req = SubtitleCleanRequest(shot_id=uuid4(), source_video_sha256=_GOOD_SHA)
    assert req.ocr_boxes == ()


def test_subtitle_clean_request_with_boxes() -> None:
    req = SubtitleCleanRequest(
        shot_id=uuid4(),
        source_video_sha256=_GOOD_SHA,
        ocr_boxes=({"x": 0.1, "y": 0.8, "w": 0.8, "h": 0.1},),
    )
    assert len(req.ocr_boxes) == 1
