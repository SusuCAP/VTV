from hashlib import sha256

import pytest
from pydantic import ValidationError
from vtv_evaluation import (
    BenchmarkEvidence,
    BenchmarkPolicy,
    GoldenDataset,
    GoldenSample,
    SampleResult,
    evaluate_release,
)


def _dataset(count: int = 4) -> GoldenDataset:
    return GoldenDataset(
        dataset_key="audio-dialogue-zh-en",
        release="golden@1",
        annotation_release="annotations@3",
        samples=tuple(
            GoldenSample(
                sample_id=f"sample-{index}",
                source_sha256=sha256(f"source-{index}".encode()).hexdigest(),
                duration_seconds=10,
                critical=index == 0,
                tags=frozenset({"dialogue", "zh"}),
            )
            for index in range(count)
        ),
    )


def _policy() -> BenchmarkPolicy:
    return BenchmarkPolicy(
        policy_key="audio-production",
        release="policy@1",
        minimum_sample_count=4,
        minimum_metric_scores={"word_accuracy": 0.8, "speaker_accuracy": 0.75},
        maximum_critical_failure_rate=0.05,
        maximum_human_reject_rate=0.1,
        maximum_cost_per_passed_second=0.02,
        maximum_p95_latency_seconds=20,
    )


def _evidence(**updates) -> BenchmarkEvidence:
    payload = {
        "technical_access_gate": "PASS",
        "rollback_test": "PASS",
        "reproducibility_test": "PASS",
        "calibration_complete": True,
        "weights_sha256": "a" * 64,
        "runtime_fingerprint": "cuda-13.0|torch-2.9|L4",
    }
    payload.update(updates)
    return BenchmarkEvidence(**payload)


def _results(count: int = 4) -> tuple[SampleResult, ...]:
    return tuple(
        SampleResult(
            sample_id=f"sample-{index}",
            metric_scores={"word_accuracy": 0.95, "speaker_accuracy": 0.9},
            latency_seconds=8 + index,
            cost_usd=0.02,
            output_duration_seconds=10,
        )
        for index in range(count)
    )


def test_release_passes_all_hard_and_statistical_gates() -> None:
    report = evaluate_release(
        model_key="audio-analysis",
        model_release="nemotron-asr@sha256:abc",
        dataset=_dataset(),
        policy=_policy(),
        evidence=_evidence(),
        results=_results(),
    )

    assert report.approved is True
    assert report.failed_gates == ()
    assert report.metrics["word_accuracy"].confidence_lower_bound == pytest.approx(0.95)
    assert report.cost_per_passed_output_second == pytest.approx(0.002)


def test_release_reports_every_failed_gate_without_short_circuiting() -> None:
    results = list(_results())
    results[0] = results[0].model_copy(
        update={
            "critical_failure": True,
            "human_rejected": True,
            "latency_seconds": 30,
            "metric_scores": {"word_accuracy": 0.1},
        }
    )
    report = evaluate_release(
        model_key="audio-analysis",
        model_release="candidate@1",
        dataset=_dataset(),
        policy=_policy(),
        evidence=_evidence(rollback_test="FAIL", calibration_complete=False),
        results=tuple(results),
    )

    assert report.approved is False
    assert "ROLLBACK_TEST" in report.failed_gates
    assert "CALIBRATION_INCOMPLETE" in report.failed_gates
    assert "CRITICAL_FAILURE_RATE" in report.failed_gates
    assert "CRITICAL_SAMPLE_FAILURE" in report.failed_gates
    assert "HUMAN_REJECT_RATE" in report.failed_gates
    assert "P95_LATENCY" in report.failed_gates
    assert "METRIC_MISSING:speaker_accuracy" in report.failed_gates


def test_benchmark_rejects_incomplete_or_duplicate_results() -> None:
    with pytest.raises(ValueError, match="sample mismatch"):
        evaluate_release(
            model_key="audio-analysis",
            model_release="candidate@1",
            dataset=_dataset(),
            policy=_policy(),
            evidence=_evidence(),
            results=_results(3),
        )

    duplicated = (_results()[0],) * 4
    with pytest.raises(ValueError, match="duplicate"):
        evaluate_release(
            model_key="audio-analysis",
            model_release="candidate@1",
            dataset=_dataset(),
            policy=_policy(),
            evidence=_evidence(),
            results=duplicated,
        )


def test_dataset_and_policy_are_immutable_and_validate_bounds() -> None:
    dataset = _dataset()
    with pytest.raises(ValidationError):
        dataset.release = "changed"  # type: ignore[misc]
    with pytest.raises(ValidationError):
        BenchmarkPolicy(
            policy_key="invalid",
            release="policy@1",
            minimum_metric_scores={"wer": 1.1},
            maximum_critical_failure_rate=0,
            maximum_human_reject_rate=0,
            maximum_cost_per_passed_second=1,
            maximum_p95_latency_seconds=1,
        )
