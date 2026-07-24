from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from vtv_media import probe_media

from .contracts import StemKind, StemOutput, StemSeparationResult


class DemucsBackend(Protocol):
    def separate(self, source: Path, output_directory: Path) -> dict[str, Path]: ...


class LazyDemucsBackend:
    def __init__(self, *, model_name: str = "htdemucs", device: str = "cuda") -> None:
        self.model_name = model_name
        self.device = device
        self._separator = None

    def _load(self):
        if self._separator is None:
            try:
                from demucs.api import Separator
            except ImportError as exc:
                raise RuntimeError("demucs is not installed in this worker image") from exc
            self._separator = Separator(model=self.model_name, device=self.device)
        return self._separator

    def preload(self) -> None:
        """Load separator weights before the first inference request."""
        self._load()

    def separate(self, source: Path, output_directory: Path) -> dict[str, Path]:
        try:
            from demucs.api import save_audio
        except ImportError as exc:
            raise RuntimeError("demucs audio writer is unavailable") from exc
        separator = self._load()
        _, separated = separator.separate_audio_file(source)
        output_directory.mkdir(parents=True, exist_ok=True)
        outputs: dict[str, Path] = {}
        for name, waveform in separated.items():
            destination = output_directory / f"{name}.wav"
            save_audio(waveform, destination, samplerate=separator.samplerate)
            outputs[str(name)] = destination
        background_waveforms = [
            waveform for name, waveform in separated.items() if str(name) != "vocals"
        ]
        if background_waveforms:
            background = background_waveforms[0].clone()
            for waveform in background_waveforms[1:]:
                background += waveform
            destination = output_directory / "no_vocals.wav"
            save_audio(background, destination, samplerate=separator.samplerate)
            outputs["no_vocals"] = destination
        return outputs


@dataclass(frozen=True, slots=True)
class DemucsStemAdapter:
    backend: DemucsBackend
    model_release: str

    def separate(self, source: Path, output_directory: Path) -> StemSeparationResult:
        outputs = self.backend.separate(source, output_directory)
        vocals = outputs.get("vocals")
        if vocals is None:
            raise ValueError("Demucs output is missing vocals stem")
        background = outputs.get("no_vocals")
        selected = [(StemKind.DIALOGUE, vocals)]
        if background is not None:
            selected.append((StemKind.BACKGROUND, background))
        stems: list[StemOutput] = []
        for kind, path in selected:
            media = probe_media(path, require_video=False)
            stream = media.audio_streams[0]
            stems.append(
                StemOutput(
                    kind=kind,
                    path=path,
                    duration_seconds=media.duration_seconds,
                    channels=stream.channels,
                    sample_rate=stream.sample_rate,
                )
            )
        source_duration = probe_media(source, require_video=False).duration_seconds
        return StemSeparationResult(
            source_duration_seconds=source_duration,
            stems=tuple(stems),
            model_release=self.model_release,
        )
