from dataclasses import dataclass
from pathlib import Path

from vtv_media import extract_audio, probe_media

from .contracts import StemKind, StemOutput, StemSeparationResult


@dataclass(frozen=True, slots=True)
class PassthroughDialogueAdapter:
    """Contract-only fallback; it does not claim semantic separation quality."""

    model_release: str = "passthrough-dialogue@1"

    def separate(self, source: Path, output_directory: Path) -> StemSeparationResult:
        output_directory.mkdir(parents=True, exist_ok=True)
        dialogue = extract_audio(source, output_directory / "dialogue.wav")
        media = probe_media(dialogue, require_video=False)
        stream = media.audio_streams[0]
        return StemSeparationResult(
            source_duration_seconds=media.duration_seconds,
            stems=(
                StemOutput(
                    kind=StemKind.DIALOGUE,
                    path=dialogue,
                    duration_seconds=media.duration_seconds,
                    channels=stream.channels,
                    sample_rate=stream.sample_rate,
                ),
            ),
            model_release=self.model_release,
        )
