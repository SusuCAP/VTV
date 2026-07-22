import pytest
from vtv_evaluation import (
    EvaluationBox,
    box_iou,
    label_f1,
    ocr_text_accuracy,
    temporal_iou,
)


def test_box_iou_scores_overlap_and_disjoint_boxes() -> None:
    reference = EvaluationBox(x=0, y=0, width=0.5, height=0.5)

    assert box_iou(reference, reference) == 1
    assert box_iou(reference, EvaluationBox(x=0.5, y=0.5, width=0.5, height=0.5)) == 0
    overlap = EvaluationBox(x=0.25, y=0, width=0.5, height=0.5)
    assert box_iou(reference, overlap) == pytest.approx(1 / 3)


def test_temporal_iou_and_scene_label_f1_are_normalized() -> None:
    assert temporal_iou((0, 2), (1, 3)) == pytest.approx(1 / 3)
    assert label_f1(("Office", "Night"), ("office", "interior")) == 0.5
    assert label_f1((), ()) == 1


def test_ocr_accuracy_handles_multilingual_width_case_and_punctuation() -> None:
    assert ocr_text_accuracy("Ｈello，合同！", "hello 合同") == 1


def test_invalid_evaluation_geometry_is_rejected() -> None:
    with pytest.raises(ValueError, match="frame bounds"):
        EvaluationBox(x=0.8, y=0, width=0.3, height=1)
    with pytest.raises(ValueError, match="positive duration"):
        temporal_iou((1, 1), (0, 1))
