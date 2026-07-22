"""Unit tests for VisualGoldenBenchmarkRunner."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from vtv_evaluation.builtin_evaluators import VISUAL_GENERATION_POLICY
from vtv_evaluation.visual_runner import (
    VisualGenerationBenchmarkPayload,
    VisualGoldenBenchmarkRunner,
    VisualGoldenSample,
)


def _make_sample(
    sample_id: str = "s001",
    route: str = "C",
    critical: bool = False,
    duration: float = 1.5,
) -> VisualGoldenSample:
    return VisualGoldenSample(
        sample_id=sample_id,
        source_sha256="a" * 64,
        reference_sha256s=("b" * 64,),
        duration_seconds=duration,
        route=route,
        critical=critical,
    )


def _make_runner() -> VisualGoldenBenchmarkRunner:
    from vtv_production.visual_adapters import PassthroughVisualGenerationAdapter

    adapter = PassthroughVisualGenerationAdapter(route_handled="C")
    return VisualGoldenBenchmarkRunner(adapter=adapter)


def test_visual_golden_sample_creation():
    sample = _make_sample()
    assert sample.sample_id == "s001"
    assert sample.route == "C"
    assert not sample.critical


def test_run_sample_returns_dict(tmp_path: Path):
    runner = _make_runner()
    sample = _make_sample()
    result, latency = runner.run_sample(sample, tmp_path)
    assert isinstance(result, dict)
    assert "sample_id" in result
    assert "metric_scores" in result
    assert latency >= 0.0


def test_run_sample_metric_scores_in_range(tmp_path: Path):
    runner = _make_runner()
    sample = _make_sample()
    result, _ = runner.run_sample(sample, tmp_path)
    for score in result["metric_scores"].values():
        assert 0.0 <= score <= 1.0


def test_run_sample_source_sha256_mismatch(tmp_path: Path):
    """A file with the wrong hash is flagged as data_contamination, not model failure."""
    runner = _make_runner()
    sample = _make_sample()
    # Write a file with the right name but wrong content
    bad_file = tmp_path / f"{sample.source_sha256[:8]}.mp4"
    bad_file.write_bytes(b"not a real video")
    result, _ = runner.run_sample(sample, tmp_path)
    assert result.get("data_contamination") is True
    assert not result.get("critical_failure")


def test_run_dataset_approved_with_enough_samples(tmp_path: Path):
    runner = _make_runner()
    # Build 10+ samples to satisfy minimum_sample_count=10
    samples = tuple(_make_sample(sample_id=f"s{i:03d}") for i in range(12))
    policy = VISUAL_GENERATION_POLICY
    model_release_id = uuid4()
    payload = runner.run_dataset(samples, policy, model_release_id, tmp_path)
    assert isinstance(payload, VisualGenerationBenchmarkPayload)
    # Passthrough scores are high enough to pass
    assert payload.approved is True


def test_run_dataset_not_approved_insufficient_samples(tmp_path: Path):
    runner = _make_runner()
    samples = tuple(_make_sample(sample_id=f"s{i:03d}") for i in range(3))  # < 10
    payload = runner.run_dataset(
        samples, VISUAL_GENERATION_POLICY, uuid4(), tmp_path
    )
    assert payload.approved is False


def test_run_dataset_isolates_exceptions(tmp_path: Path, monkeypatch):
    """One sample raising an exception should not abort the rest."""
    from vtv_production.visual_adapters import PassthroughVisualGenerationAdapter

    call_count = {"n": 0}

    original_generate = PassthroughVisualGenerationAdapter.generate

    def patched_generate(self, request, source_video, output_directory, mask=None):
        call_count["n"] += 1
        if call_count["n"] == 3:
            raise RuntimeError("simulated GPU OOM")
        return original_generate(self, request, source_video, output_directory, mask)

    monkeypatch.setattr(PassthroughVisualGenerationAdapter, "generate", patched_generate)

    runner = _make_runner()
    samples = tuple(_make_sample(sample_id=f"s{i:03d}") for i in range(12))
    payload = runner.run_dataset(
        samples, VISUAL_GENERATION_POLICY, uuid4(), tmp_path
    )
    # The errored sample's result may be counted; others should still appear
    assert len(payload.results) >= 10


def test_visual_generation_benchmark_payload_fields(tmp_path: Path):
    runner = _make_runner()
    samples = tuple(_make_sample(sample_id=f"s{i:03d}") for i in range(12))
    model_id = uuid4()
    payload = runner.run_dataset(samples, VISUAL_GENERATION_POLICY, model_id, tmp_path)
    assert payload.model_release_id == model_id
    assert payload.policy_key == VISUAL_GENERATION_POLICY.policy_key
    assert isinstance(payload.evidence, dict)


def test_visual_generation_policy_structure():
    from vtv_evaluation.builtin_evaluators import VISUAL_GENERATION_POLICY

    assert VISUAL_GENERATION_POLICY.minimum_sample_count == 10
    assert "character_identity_score" in VISUAL_GENERATION_POLICY.minimum_metric_scores
    assert VISUAL_GENERATION_POLICY.maximum_critical_failure_rate == 0.05
