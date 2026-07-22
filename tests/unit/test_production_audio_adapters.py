from pathlib import Path

import pytest
from vtv_analysis import (
    AudioAnalysisPipeline,
    FasterWhisperAsrAdapter,
    FasterWhisperVadAdapter,
    LazyPyannoteBackend,
    PyannoteDiarizationAdapter,
    RawSpeakerTurn,
    RawSpeech,
    RawTranscript,
    RawWord,
)


class FakeWhisperBackend:
    def detect(self, audio_path: Path) -> tuple[RawSpeech, ...]:
        assert audio_path.name == "dialogue.wav"
        return (RawSpeech(0.1, 1.9, 0.97),)

    def transcribe(
        self, audio_path: Path, language_hint: str | None
    ) -> tuple[RawTranscript, ...]:
        assert language_hint == "zh-CN"
        return (
            RawTranscript(
                0.1,
                1.9,
                "你好",
                "zh-CN",
                (RawWord(0.1, 0.8, "你", 0.95), RawWord(0.8, 1.9, "好", 0.93)),
            ),
        )


class FakeDiarizationBackend:
    def identify(self, audio_path: Path) -> tuple[RawSpeakerTurn, ...]:
        return (RawSpeakerTurn(0.1, 1.9, "cluster:SPEAKER_00", 0.5),)


def test_production_audio_adapters_preserve_timestamps_and_releases(tmp_path: Path) -> None:
    audio = tmp_path / "dialogue.wav"
    audio.write_bytes(b"fake-wave-for-contract")
    whisper = FakeWhisperBackend()
    pipeline = AudioAnalysisPipeline(
        vad=FasterWhisperVadAdapter(whisper, "silero-vad@faster-whisper-1.2.1"),
        asr=FasterWhisperAsrAdapter(whisper, "whisper-large-v3@ct2"),
        diarization=PyannoteDiarizationAdapter(
            FakeDiarizationBackend(), "pyannote-community-1@main"
        ),
    )

    result = pipeline.analyze(audio.resolve().as_uri(), 2.0, "zh-CN")

    assert result.transcript[0].words[1].text == "好"
    assert result.speakers[0].speaker_id == "cluster:SPEAKER_00"
    assert pipeline.asr.model_release == "whisper-large-v3@ct2"


def test_vad_rejects_backend_timestamps_outside_media(tmp_path: Path) -> None:
    audio = tmp_path / "dialogue.wav"
    audio.write_bytes(b"fake")

    class InvalidBackend(FakeWhisperBackend):
        def detect(self, audio_path: Path) -> tuple[RawSpeech, ...]:
            return (RawSpeech(0, 3, 1),)

    with pytest.raises(ValueError, match="exceeds"):
        FasterWhisperVadAdapter(InvalidBackend(), "vad@1").detect(
            audio.resolve().as_uri(), 2
        )


def test_production_adapters_reject_non_local_uri() -> None:
    with pytest.raises(ValueError, match="requires local media"):
        FasterWhisperVadAdapter(FakeWhisperBackend(), "vad@1").detect(
            "s3://bucket/audio.wav", 2
        )


def test_pyannote_gated_weights_require_token(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("HF_TOKEN", raising=False)
    audio = tmp_path / "dialogue.wav"
    audio.write_bytes(b"fake")

    with pytest.raises(RuntimeError, match="HF_TOKEN"):
        LazyPyannoteBackend().identify(audio)
