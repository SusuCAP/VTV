import pytest
from vtv_evaluation import (
    TimedSpeakerLabel,
    diarization_overlap_accuracy,
    transcript_accuracy,
)


def test_transcript_accuracy_normalizes_case_width_and_punctuation() -> None:
    assert transcript_accuracy("Ｈello，你好！", "hello 你好") == 1
    assert transcript_accuracy("你好世界", "你好世") == pytest.approx(0.75)


def test_diarization_score_is_invariant_to_cluster_names() -> None:
    reference = (
        TimedSpeakerLabel(0, 2, "alice"),
        TimedSpeakerLabel(2, 4, "bob"),
    )
    hypothesis = (
        TimedSpeakerLabel(0, 2, "cluster:1"),
        TimedSpeakerLabel(2, 4, "cluster:0"),
    )

    assert diarization_overlap_accuracy(reference, hypothesis) == 1


def test_diarization_score_penalizes_missing_reference_time() -> None:
    reference = (TimedSpeakerLabel(0, 4, "alice"),)
    hypothesis = (TimedSpeakerLabel(0, 3, "cluster:0"),)

    assert diarization_overlap_accuracy(reference, hypothesis) == pytest.approx(0.75)
