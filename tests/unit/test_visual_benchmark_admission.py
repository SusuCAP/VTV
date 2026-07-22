"""Unit tests for visual model benchmark admission gate (Phase 4 exit condition)."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from vtv_evaluation.benchmark_runner_cli import run_visual_benchmark
from vtv_evaluation.builtin_evaluators import VISUAL_GENERATION_POLICY


def test_run_visual_benchmark_returns_dict(tmp_path: Path) -> None:
    """run_visual_benchmark returns a plain dict."""
    result = run_visual_benchmark(uuid4(), tmp_path)
    assert isinstance(result, dict)


def test_run_visual_benchmark_required_fields_present(tmp_path: Path) -> None:
    """Returned dict contains all fields required by the benchmark API payload."""
    result = run_visual_benchmark(uuid4(), tmp_path)
    required = {
        "model_release_id",
        "dataset_fingerprint",
        "policy_key",
        "approved",
        "weights_sha256",
        "runtime_fingerprint",
        "technical_access_gate",
        "rollback_test",
        "reproducibility_test",
        "calibration_complete",
        "sample_results",
    }
    assert required.issubset(result.keys())


def test_run_visual_benchmark_approved_true_passthrough(tmp_path: Path) -> None:
    """Passthrough adapter scores satisfy VISUAL_GENERATION_POLICY → approved=True."""
    result = run_visual_benchmark(uuid4(), tmp_path, sample_count=12)
    assert result["approved"] is True


def test_run_visual_benchmark_approved_false_insufficient_samples(tmp_path: Path) -> None:
    """Fewer samples than minimum_sample_count (10) → approved=False."""
    result = run_visual_benchmark(uuid4(), tmp_path, sample_count=3)
    assert result["approved"] is False


def test_run_visual_benchmark_dataset_fingerprint_matches_policy(tmp_path: Path) -> None:
    """dataset_fingerprint must equal VISUAL_GENERATION_POLICY.fingerprint."""
    result = run_visual_benchmark(uuid4(), tmp_path)
    assert result["dataset_fingerprint"] == VISUAL_GENERATION_POLICY.fingerprint


def test_run_visual_benchmark_sample_results_length(tmp_path: Path) -> None:
    """sample_results list length equals sample_count when no contamination occurs."""
    result = run_visual_benchmark(uuid4(), tmp_path, sample_count=12)
    assert len(result["sample_results"]) == 12


def test_run_visual_benchmark_compatible_structure(tmp_path: Path) -> None:
    """Each entry in sample_results can be used to instantiate SampleResult."""
    from vtv_evaluation.contracts import SampleResult

    result = run_visual_benchmark(uuid4(), tmp_path, sample_count=12)
    for sr in result["sample_results"]:
        obj = SampleResult(
            sample_id=sr["sample_id"],
            metric_scores=sr["metric_scores"],
            critical_failure=sr["critical_failure"],
            human_rejected=sr["human_rejected"],
            latency_seconds=sr["latency_seconds"],
            cost_usd=sr["cost_usd"],
            output_duration_seconds=sr["output_duration_seconds"],
            error_class=sr.get("error_class"),
        )
        assert obj.sample_id == sr["sample_id"]


def test_run_visual_benchmark_policy_key_matches(tmp_path: Path) -> None:
    """policy_key in the payload matches VISUAL_GENERATION_POLICY.policy_key."""
    result = run_visual_benchmark(uuid4(), tmp_path)
    assert result["policy_key"] == VISUAL_GENERATION_POLICY.policy_key
