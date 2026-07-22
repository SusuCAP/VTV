from .contracts import SubtitleDocument


def render_srt(document: SubtitleDocument) -> str:
    blocks = [
        f"{cue.index}\n{_time(cue.start_seconds, ',')} --> {_time(cue.end_seconds, ',')}\n"
        f"{cue.text.strip()}"
        for cue in document.cues
    ]
    return "\n\n".join(blocks) + "\n"


def render_vtt(document: SubtitleDocument) -> str:
    blocks = [
        f"{_time(cue.start_seconds, '.')} --> {_time(cue.end_seconds, '.')}\n"
        f"{cue.text.strip()}"
        for cue in document.cues
    ]
    return "WEBVTT\n\n" + "\n\n".join(blocks) + "\n"


def _time(seconds: float, separator: str) -> str:
    total_ms = round(seconds * 1000)
    hours, remainder = divmod(total_ms, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    whole_seconds, milliseconds = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{whole_seconds:02d}{separator}{milliseconds:03d}"
