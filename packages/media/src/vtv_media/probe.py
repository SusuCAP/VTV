import json
from fractions import Fraction
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from .process import MediaProcessError, run_media_process


class MediaProbeError(ValueError):
    pass


class MediaStream(BaseModel):
    index: int
    codec_type: Literal["video", "audio", "subtitle", "data", "attachment", "unknown"]
    codec_name: str | None = None
    duration_seconds: float | None = Field(default=None, ge=0)
    width: int | None = Field(default=None, ge=1)
    height: int | None = Field(default=None, ge=1)
    frame_rate: float | None = Field(default=None, ge=0)
    sample_rate: int | None = Field(default=None, ge=1)
    channels: int | None = Field(default=None, ge=1)


class MediaProbe(BaseModel):
    path: Path
    format_name: str
    duration_seconds: float = Field(gt=0)
    size_bytes: int = Field(gt=0)
    bit_rate: int | None = Field(default=None, ge=0)
    streams: list[MediaStream]

    @property
    def video_streams(self) -> list[MediaStream]:
        return [stream for stream in self.streams if stream.codec_type == "video"]

    @property
    def audio_streams(self) -> list[MediaStream]:
        return [stream for stream in self.streams if stream.codec_type == "audio"]


def _optional_float(value: Any) -> float | None:
    if value in (None, "", "N/A"):
        return None
    return float(value)


def _optional_int(value: Any) -> int | None:
    if value in (None, "", "N/A"):
        return None
    return int(value)


def _frame_rate(value: Any) -> float | None:
    if value in (None, "", "0/0", "N/A"):
        return None
    return float(Fraction(str(value)))


def probe_media(
    path: Path,
    *,
    require_video: bool = True,
    ffprobe_executable: str = "ffprobe",
    timeout_seconds: int = 60,
) -> MediaProbe:
    if not path.is_file():
        raise MediaProbeError(f"media file does not exist: {path}")
    try:
        result = run_media_process(
            [
                ffprobe_executable,
                "-v",
                "error",
                "-show_format",
                "-show_streams",
                "-of",
                "json",
                path,
            ],
            timeout_seconds=timeout_seconds,
        )
    except MediaProcessError as exc:
        raise MediaProbeError(str(exc)) from exc
    try:
        raw = json.loads(result.stdout)
        raw_format = raw["format"]
        duration = float(raw_format["duration"])
        streams = [
            MediaStream(
                index=int(stream["index"]),
                codec_type=(
                    stream.get("codec_type")
                    if stream.get("codec_type")
                    in {"video", "audio", "subtitle", "data", "attachment"}
                    else "unknown"
                ),
                codec_name=stream.get("codec_name"),
                duration_seconds=_optional_float(stream.get("duration")),
                width=_optional_int(stream.get("width")),
                height=_optional_int(stream.get("height")),
                frame_rate=_frame_rate(stream.get("avg_frame_rate")),
                sample_rate=_optional_int(stream.get("sample_rate")),
                channels=_optional_int(stream.get("channels")),
            )
            for stream in raw.get("streams", [])
        ]
        probe = MediaProbe(
            path=path.resolve(),
            format_name=str(raw_format["format_name"]),
            duration_seconds=duration,
            size_bytes=int(raw_format.get("size") or path.stat().st_size),
            bit_rate=_optional_int(raw_format.get("bit_rate")),
            streams=streams,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise MediaProbeError(f"invalid ffprobe response: {exc}") from exc
    if require_video and not probe.video_streams:
        raise MediaProbeError("media does not contain a video stream")
    if not probe.streams:
        raise MediaProbeError("media does not contain a supported stream")
    return probe
