import re
from itertools import pairwise
from pathlib import Path

from pydantic import BaseModel, Field

from .probe import probe_media
from .process import run_media_process

PTS_TIME = re.compile(r"pts_time:([0-9]+(?:\.[0-9]+)?)")


class ShotBoundary(BaseModel):
    shot_no: int = Field(ge=1)
    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(gt=0)


def detect_shots(
    source: Path,
    *,
    threshold: float = 0.30,
    minimum_shot_seconds: float = 0.20,
    ffmpeg_executable: str = "ffmpeg",
    timeout_seconds: int = 1800,
) -> list[ShotBoundary]:
    if not 0 < threshold < 1:
        raise ValueError("scene threshold must be between 0 and 1")
    probe = probe_media(source)
    result = run_media_process(
        [
            ffmpeg_executable,
            "-nostdin",
            "-i",
            source,
            "-an",
            "-vf",
            f"select='gt(scene,{threshold})',showinfo",
            "-f",
            "null",
            "-",
        ],
        timeout_seconds=timeout_seconds,
    )
    candidates = sorted(
        {
            float(match.group(1))
            for match in PTS_TIME.finditer(result.stderr)
            if 0 < float(match.group(1)) < probe.duration_seconds
        }
    )
    accepted: list[float] = []
    previous = 0.0
    for candidate in candidates:
        if candidate - previous >= minimum_shot_seconds:
            accepted.append(candidate)
            previous = candidate
    points = [0.0, *accepted, probe.duration_seconds]
    return [
        ShotBoundary(shot_no=index + 1, start_seconds=start, end_seconds=end)
        for index, (start, end) in enumerate(pairwise(points))
        if end - start > 0
    ]
