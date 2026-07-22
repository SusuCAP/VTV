import pytest
from vtv_assembly import (
    PictureConformRequest,
    PictureEdit,
    SubtitleCue,
    SubtitleDocument,
    render_srt,
    render_vtt,
)


def test_subtitle_rendering_is_deterministic_and_uses_standard_timecodes() -> None:
    document = SubtitleDocument(
        locale="en-US",
        cues=(
            SubtitleCue(index=1, start_seconds=0, end_seconds=1.234, text="Hello."),
            SubtitleCue(index=2, start_seconds=61.5, end_seconds=62.75, text="Goodbye."),
        ),
    )

    assert "00:00:00,000 --> 00:00:01,234" in render_srt(document)
    assert "00:01:01.500 --> 00:01:02.750" in render_vtt(document)
    assert render_vtt(document).startswith("WEBVTT\n\n")


def test_subtitle_document_rejects_overlap_and_non_contiguous_indices() -> None:
    with pytest.raises(ValueError, match="non-overlapping"):
        SubtitleDocument(
            locale="en-US",
            cues=(
                SubtitleCue(index=1, start_seconds=0, end_seconds=2, text="One"),
                SubtitleCue(index=2, start_seconds=1, end_seconds=3, text="Two"),
            ),
        )
    with pytest.raises(ValueError, match="contiguous"):
        SubtitleDocument(
            locale="en-US",
            cues=(SubtitleCue(index=2, start_seconds=0, end_seconds=1, text="Two"),),
        )


def test_picture_conform_rejects_overlap_duplicate_assets_and_episode_overflow() -> None:
    with pytest.raises(ValueError, match="non-overlapping"):
        PictureConformRequest(
            source_video_sha256="a" * 64,
            duration_seconds=3,
            edits=(
                PictureEdit(
                    shot_id="shot-1",
                    replacement_sha256="b" * 64,
                    start_seconds=0,
                    end_seconds=2,
                ),
                PictureEdit(
                    shot_id="shot-2",
                    replacement_sha256="c" * 64,
                    start_seconds=1,
                    end_seconds=3,
                ),
            ),
        )
    with pytest.raises(ValueError, match="unique"):
        PictureConformRequest(
            source_video_sha256="a" * 64,
            duration_seconds=3,
            edits=(
                PictureEdit(
                    shot_id="shot-1",
                    replacement_sha256="b" * 64,
                    start_seconds=0,
                    end_seconds=1,
                ),
                PictureEdit(
                    shot_id="shot-2",
                    replacement_sha256="b" * 64,
                    start_seconds=1,
                    end_seconds=2,
                ),
            ),
        )
    with pytest.raises(ValueError, match="exceeds"):
        PictureConformRequest(
            source_video_sha256="a" * 64,
            duration_seconds=2,
            edits=(
                PictureEdit(
                    shot_id="shot-1",
                    replacement_sha256="b" * 64,
                    start_seconds=1,
                    end_seconds=3,
                ),
            ),
        )
