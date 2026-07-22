from uuid import uuid4

import pytest
from vtv_db.models import MediaAsset
from vtv_orchestrator.scheduler import _resolve_assembly_inputs


def _asset(stage_type: str, content_type: str, digest: str) -> MediaAsset:
    return MediaAsset(
        id=uuid4(),
        workspace_id=uuid4(),
        project_id=uuid4(),
        object_uri=f"s3://bucket/{stage_type.lower()}",
        sha256=digest * 64,
        size_bytes=10,
        content_type=content_type,
        metadata_json={"stage_type": stage_type},
    )


def test_scheduler_binds_only_authoritative_master_inputs() -> None:
    picture = _asset("PICTURE_CONFORM", "video/mp4", "a")
    mix = _asset("AUDIO_MIX", "audio/wav", "b")
    srt = _asset("SUBTITLE_RENDER", "application/x-subrip", "c")
    vtt = _asset("SUBTITLE_RENDER", "text/vtt", "d")
    template = {
        "duration_seconds": 60,
        "width": 1080,
        "height": 1920,
        "fps": 24,
        "video_codec": "h264",
        "audio_codec": "aac",
        "burn_subtitles": True,
        "subtitle_document": {"locale": "en-US", "cues": []},
    }

    selected, request = _resolve_assembly_inputs(
        [picture, mix, srt, vtt], template
    )

    assert selected == [picture, mix, srt]
    assert request["source_video_sha256"] == "a" * 64
    assert request["mixed_audio_sha256"] == "b" * 64
    assert request["subtitle_sha256"] == "c" * 64


def test_scheduler_rejects_missing_or_ambiguous_master_inputs() -> None:
    picture = _asset("PICTURE_CONFORM", "video/mp4", "a")
    mix = _asset("AUDIO_MIX", "audio/wav", "b")
    template = {"burn_subtitles": True}

    with pytest.raises(ValueError, match="SRT"):
        _resolve_assembly_inputs([picture, mix], template)
    with pytest.raises(ValueError, match="one picture"):
        _resolve_assembly_inputs([picture, picture, mix], {"burn_subtitles": False})
