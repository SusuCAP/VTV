from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError
from vtv_evaluation.builtin_evaluators import BUILTIN_EVALUATORS
from vtv_evaluation.contracts import (
    EvaluatorReleaseCreate,
    MetricDefinition,
    QcEvidenceCreate,
)

# --- MetricDefinition ---

def test_metric_definition_defaults() -> None:
    m = MetricDefinition(metric_name="foo", metric_version="v1")
    assert m.description == ""
    assert m.hard_failure_below is None


def test_metric_definition_hard_failure_below_valid() -> None:
    m = MetricDefinition(
        metric_name="foo", metric_version="v1", hard_failure_below=0.5
    )
    assert m.hard_failure_below == 0.5


def test_metric_definition_hard_failure_below_zero() -> None:
    m = MetricDefinition(
        metric_name="duration_deviation", metric_version="v1", hard_failure_below=0.0
    )
    assert m.hard_failure_below == 0.0


def test_metric_definition_hard_failure_below_out_of_range() -> None:
    with pytest.raises(ValidationError):
        MetricDefinition(
            metric_name="foo", metric_version="v1", hard_failure_below=1.5
        )


def test_metric_definition_hard_failure_below_negative() -> None:
    with pytest.raises(ValidationError):
        MetricDefinition(
            metric_name="foo", metric_version="v1", hard_failure_below=-0.1
        )


def test_metric_definition_empty_metric_name() -> None:
    with pytest.raises(ValidationError):
        MetricDefinition(metric_name="", metric_version="v1")


# --- EvaluatorReleaseCreate ---

def test_evaluator_release_create_valid() -> None:
    er = EvaluatorReleaseCreate(
        evaluator_key="my_evaluator",
        release_name="vtv.my-evaluator.v1",
        metric_definitions=(
            MetricDefinition(metric_name="score_a", metric_version="v1"),
        ),
        thresholds={"score_a": 0.7},
    )
    assert er.evaluator_key == "my_evaluator"
    assert er.thresholds["score_a"] == 0.7


def test_evaluator_release_create_threshold_key_not_in_definitions() -> None:
    with pytest.raises(ValidationError, match="not in metric definitions"):
        EvaluatorReleaseCreate(
            evaluator_key="my_evaluator",
            release_name="vtv.my-evaluator.v1",
            metric_definitions=(
                MetricDefinition(metric_name="score_a", metric_version="v1"),
            ),
            thresholds={"unknown_metric": 0.5},
        )


def test_evaluator_release_create_empty_metric_definitions() -> None:
    with pytest.raises(ValidationError):
        EvaluatorReleaseCreate(
            evaluator_key="my_evaluator",
            release_name="vtv.my-evaluator.v1",
            metric_definitions=(),
        )


def test_evaluator_release_create_no_thresholds_is_valid() -> None:
    er = EvaluatorReleaseCreate(
        evaluator_key="my_evaluator",
        release_name="vtv.my-evaluator.v1",
        metric_definitions=(
            MetricDefinition(metric_name="score_a", metric_version="v1"),
        ),
    )
    assert er.thresholds == {}


# --- QcEvidenceCreate ---

def test_qc_evidence_create_valid() -> None:
    ev = QcEvidenceCreate(
        render_variant_id=uuid4(),
        evaluator_release_id=uuid4(),
        results=(
            {
                "metric_name": "frame_integrity",
                "metric_version": "v1",
                "evaluator_release": "vtv.visual-technical.v1",
                "score": 0.9,
                "verdict": "PASS",
                "hard_failure": False,
            },
        ),
    )
    assert len(ev.results) == 1


def test_qc_evidence_create_empty_results_is_valid() -> None:
    # No min_length constraint on results in the spec
    ev = QcEvidenceCreate(
        render_variant_id=uuid4(),
        evaluator_release_id=uuid4(),
        results=(),
    )
    assert ev.results == ()


# --- BUILTIN_EVALUATORS ---

def test_builtin_evaluators_count() -> None:
    assert len(BUILTIN_EVALUATORS) == 5


def test_builtin_evaluators_all_valid() -> None:
    keys = {e.evaluator_key for e in BUILTIN_EVALUATORS}
    assert keys == {
        "visual_technical",
        "visual_identity",
        "visual_continuity",
        "lipsync_qc",
        "audio_continuity",
    }


def test_builtin_evaluators_thresholds_within_definitions() -> None:
    for evaluator in BUILTIN_EVALUATORS:
        metric_names = {m.metric_name for m in evaluator.metric_definitions}
        for key in evaluator.thresholds:
            assert key in metric_names, (
                f"{evaluator.evaluator_key}: threshold key {key!r} not in definitions"
            )


def test_builtin_evaluators_have_release_names() -> None:
    for evaluator in BUILTIN_EVALUATORS:
        assert evaluator.release_name.startswith("vtv.")
