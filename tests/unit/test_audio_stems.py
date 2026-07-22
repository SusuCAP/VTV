from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from vtv_audio import DemucsStemAdapter, StemKind, StemOutput, StemSeparationResult


def _stem(kind: StemKind, duration: float = 2) -> StemOutput:
    return StemOutput(
        kind=kind,
        path=Path(f"{kind.lower()}.wav"),
        duration_seconds=duration,
        channels=2,
        sample_rate=48000,
    )


def test_stem_result_requires_dialogue_and_unique_kinds() -> None:
    with pytest.raises(ValidationError, match="dialogue"):
        StemSeparationResult(
            source_duration_seconds=2,
            stems=(_stem(StemKind.BACKGROUND),),
            model_release="demucs@1",
        )
    with pytest.raises(ValidationError, match="unique"):
        StemSeparationResult(
            source_duration_seconds=2,
            stems=(_stem(StemKind.DIALOGUE), _stem(StemKind.DIALOGUE)),
            model_release="demucs@1",
        )


def test_stem_result_enforces_source_duration() -> None:
    with pytest.raises(ValidationError, match="50 ms"):
        StemSeparationResult(
            source_duration_seconds=2,
            stems=(_stem(StemKind.DIALOGUE, 2.1),),
            model_release="demucs@1",
        )


def test_demucs_adapter_maps_only_explicit_vocals_and_full_background(
    monkeypatch, tmp_path: Path
) -> None:
    source = tmp_path / "source.wav"
    vocals = tmp_path / "vocals.wav"
    background = tmp_path / "no_vocals.wav"
    for path in (source, vocals, background):
        path.write_bytes(b"audio")

    class Backend:
        def separate(self, source: Path, output_directory: Path) -> dict[str, Path]:
            return {"vocals": vocals, "no_vocals": background}

    media = SimpleNamespace(
        duration_seconds=2,
        audio_streams=[SimpleNamespace(channels=2, sample_rate=48000)],
    )
    monkeypatch.setattr("vtv_audio.demucs.probe_media", lambda *args, **kwargs: media)

    result = DemucsStemAdapter(Backend(), "demucs@1").separate(source, tmp_path)

    assert [stem.kind for stem in result.stems] == [StemKind.DIALOGUE, StemKind.BACKGROUND]
