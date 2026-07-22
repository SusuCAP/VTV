from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from itertools import permutations


@dataclass(frozen=True, slots=True)
class TimedSpeakerLabel:
    start_seconds: float
    end_seconds: float
    speaker_id: str

    def __post_init__(self) -> None:
        if self.start_seconds < 0 or self.end_seconds <= self.start_seconds:
            raise ValueError("speaker label must have a positive interval")
        if not self.speaker_id:
            raise ValueError("speaker label requires a speaker ID")


def transcript_accuracy(reference: str, hypothesis: str) -> float:
    """Unicode-aware normalized character accuracy for multilingual ASR gating."""
    expected = _normalized_characters(reference)
    actual = _normalized_characters(hypothesis)
    if not expected:
        return 1.0 if not actual else 0.0
    distance = _edit_distance(expected, actual)
    return max(0.0, 1.0 - distance / len(expected))


def diarization_overlap_accuracy(
    reference: tuple[TimedSpeakerLabel, ...],
    hypothesis: tuple[TimedSpeakerLabel, ...],
) -> float:
    """Score speaker overlap after finding the best anonymous cluster-to-speaker mapping."""
    if not reference:
        return 1.0 if not hypothesis else 0.0
    reference_ids = sorted({item.speaker_id for item in reference})
    hypothesis_ids = sorted({item.speaker_id for item in hypothesis})
    if not hypothesis_ids:
        return 0.0
    if len(reference_ids) > 8 or len(hypothesis_ids) > 8:
        raise ValueError("exact diarization scoring supports at most eight speakers")
    padded_reference = reference_ids + [f"__none_{index}" for index in range(
        max(0, len(hypothesis_ids) - len(reference_ids))
    )]
    total_reference = sum(item.end_seconds - item.start_seconds for item in reference)
    best_overlap = 0.0
    for assigned in permutations(padded_reference, len(hypothesis_ids)):
        mapping = dict(zip(hypothesis_ids, assigned, strict=True))
        overlap = sum(
            _overlap(expected, actual)
            for expected in reference
            for actual in hypothesis
            if mapping[actual.speaker_id] == expected.speaker_id
        )
        best_overlap = max(best_overlap, overlap)
    return min(1.0, best_overlap / total_reference)


def _normalized_characters(value: str) -> tuple[str, ...]:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return tuple(character for character in normalized if character.isalnum())


def _edit_distance(expected: tuple[str, ...], actual: tuple[str, ...]) -> int:
    previous = list(range(len(actual) + 1))
    for row, expected_character in enumerate(expected, 1):
        current = [row]
        for column, actual_character in enumerate(actual, 1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[column] + 1,
                    previous[column - 1] + (expected_character != actual_character),
                )
            )
        previous = current
    return previous[-1]


def _overlap(expected: TimedSpeakerLabel, actual: TimedSpeakerLabel) -> float:
    return max(
        0.0,
        min(expected.end_seconds, actual.end_seconds)
        - max(expected.start_seconds, actual.start_seconds),
    )
