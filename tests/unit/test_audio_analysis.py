import pytest
from pydantic import ValidationError
from vtv_analysis import (
    AudioAnalysis,
    AudioAnalysisPipeline,
    DeterministicAsr,
    DeterministicDiarization,
    DeterministicVad,
    SpeechSegment,
)


def test_deterministic_audio_pipeline_produces_aligned_contracts() -> None:
    pipeline = AudioAnalysisPipeline(
        vad=DeterministicVad(),
        asr=DeterministicAsr(text="你好世界"),
        diarization=DeterministicDiarization(),
    )

    result = pipeline.analyze("file:///episode.wav", 3.5, "zh-CN")

    assert result.language == "zh-CN"
    assert result.speech[0].end_seconds == 3.5
    assert result.transcript[0].words[0].text == "你好世界"
    assert result.speakers[0].speaker_id == "speaker-001"


def test_timed_span_rejects_reversed_interval() -> None:
    with pytest.raises(ValidationError, match="end_seconds"):
        SpeechSegment(start_seconds=2, end_seconds=1, confidence=0.9)


def test_audio_analysis_rejects_span_outside_duration() -> None:
    with pytest.raises(ValidationError, match="exceeds audio duration"):
        AudioAnalysis(
            duration_seconds=1,
            language="zh-CN",
            speech=(SpeechSegment(start_seconds=0, end_seconds=2, confidence=1),),
            transcript=(),
            speakers=(),
        )
