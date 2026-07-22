from pathlib import Path
from uuid import uuid4

from .process import run_media_process


def _temporary_output(output: Path) -> Path:
    return output.with_name(f".{output.stem}.{uuid4().hex}.tmp{output.suffix}")


def generate_proxy(
    source: Path,
    output: Path,
    *,
    max_width: int = 720,
    crf: int = 28,
    ffmpeg_executable: str = "ffmpeg",
    timeout_seconds: int = 1800,
) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = _temporary_output(output)
    try:
        run_media_process(
            [
                ffmpeg_executable,
                "-nostdin",
                "-y",
                "-i",
                source,
                "-map",
                "0:v:0",
                "-map",
                "0:a?",
                "-vf",
                f"scale={max_width}:-2:force_original_aspect_ratio=decrease",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                str(crf),
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-b:a",
                "128k",
                "-movflags",
                "+faststart",
                temporary,
            ],
            timeout_seconds=timeout_seconds,
        )
        temporary.replace(output)
    finally:
        temporary.unlink(missing_ok=True)
    return output


def extract_audio(
    source: Path,
    output: Path,
    *,
    sample_rate: int = 48_000,
    ffmpeg_executable: str = "ffmpeg",
    timeout_seconds: int = 1800,
) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = _temporary_output(output)
    try:
        run_media_process(
            [
                ffmpeg_executable,
                "-nostdin",
                "-y",
                "-i",
                source,
                "-map",
                "0:a:0",
                "-vn",
                "-ac",
                "2",
                "-ar",
                str(sample_rate),
                "-c:a",
                "pcm_s16le",
                temporary,
            ],
            timeout_seconds=timeout_seconds,
        )
        temporary.replace(output)
    finally:
        temporary.unlink(missing_ok=True)
    return output
