from __future__ import annotations

from dataclasses import dataclass

from .audio_metrics import transcript_accuracy


@dataclass(frozen=True, slots=True)
class EvaluationBox:
    x: float
    y: float
    width: float
    height: float

    def __post_init__(self) -> None:
        if (
            self.x < 0
            or self.y < 0
            or self.width <= 0
            or self.height <= 0
            or self.x + self.width > 1
            or self.y + self.height > 1
        ):
            raise ValueError("evaluation box must fit inside normalized frame bounds")


def box_iou(reference: EvaluationBox, hypothesis: EvaluationBox) -> float:
    """Intersection over union for normalized detection boxes."""
    left = max(reference.x, hypothesis.x)
    top = max(reference.y, hypothesis.y)
    right = min(reference.x + reference.width, hypothesis.x + hypothesis.width)
    bottom = min(reference.y + reference.height, hypothesis.y + hypothesis.height)
    intersection = max(0.0, right - left) * max(0.0, bottom - top)
    union = (
        reference.width * reference.height
        + hypothesis.width * hypothesis.height
        - intersection
    )
    return intersection / union


def temporal_iou(
    reference: tuple[float, float], hypothesis: tuple[float, float]
) -> float:
    """Intersection over union for positive media time intervals."""
    _validate_interval(reference)
    _validate_interval(hypothesis)
    intersection = max(
        0.0, min(reference[1], hypothesis[1]) - max(reference[0], hypothesis[0])
    )
    union = max(reference[1], hypothesis[1]) - min(reference[0], hypothesis[0])
    return intersection / union


def label_f1(reference: tuple[str, ...], hypothesis: tuple[str, ...]) -> float:
    """Case-insensitive set F1 for scene labels."""
    expected = {value.strip().casefold() for value in reference if value.strip()}
    actual = {value.strip().casefold() for value in hypothesis if value.strip()}
    if not expected:
        return 1.0 if not actual else 0.0
    if not actual:
        return 0.0
    true_positive = len(expected & actual)
    precision = true_positive / len(actual)
    recall = true_positive / len(expected)
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


def ocr_text_accuracy(reference: str, hypothesis: str) -> float:
    """Unicode-aware OCR text accuracy aligned with multilingual ASR normalization."""
    return transcript_accuracy(reference, hypothesis)


def _validate_interval(interval: tuple[float, float]) -> None:
    if interval[0] < 0 or interval[1] <= interval[0]:
        raise ValueError("evaluation interval must have positive duration")
