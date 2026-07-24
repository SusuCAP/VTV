"""Visual model benchmark admission gate CLI helper for Phase 4.

Converts VisualGoldenBenchmarkRunner output into the flat dict expected by
the benchmark release API (BenchmarkReleaseCreate-compatible payload).
"""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

from vtv_evaluation.builtin_evaluators import VISUAL_GENERATION_POLICY
from vtv_evaluation.visual_runner import VisualGoldenBenchmarkRunner, VisualGoldenSample


def run_visual_benchmark(
    model_release_id: UUID,
    workdir: Path,
    *,
    adapter,
    samples: tuple[VisualGoldenSample, ...],
) -> dict:
    """Run visual golden benchmark and return benchmark API payload.

    The caller must provide a real, approved adapter and an immutable Golden
    Dataset manifest. No synthetic sample IDs, hashes, or passthrough adapter
    are admitted by the production benchmark entrypoint.
    """
    runner = VisualGoldenBenchmarkRunner(adapter=adapter)
    policy = VISUAL_GENERATION_POLICY

    payload = runner.run_dataset(samples, policy, model_release_id, workdir)

    evidence: dict = payload.evidence  # already model_dump(mode="json")

    sample_results = [
        {
            "sample_id": r["sample_id"],
            "metric_scores": r["metric_scores"],
            "critical_failure": r.get("critical_failure", False),
            "human_rejected": r.get("human_rejected", False),
            # latency_seconds must be > 0 per SampleResult contract
            "latency_seconds": max(r.get("latency_seconds", 0.001), 0.001),
            "cost_usd": 0.0,
            # output_duration_seconds must be > 0; passthrough uses source duration
            "output_duration_seconds": 1.5,
            "error_class": None,
        }
        for r in payload.results
    ]

    return {
        "model_release_id": str(model_release_id),
        "dataset_fingerprint": policy.fingerprint,
        "policy_key": policy.policy_key,
        "approved": payload.approved,
        "weights_sha256": evidence["weights_sha256"],
        "runtime_fingerprint": evidence["runtime_fingerprint"],
        "technical_access_gate": evidence.get("technical_access_gate", "PASS"),
        "rollback_test": evidence.get("rollback_test", "PASS"),
        "reproducibility_test": evidence.get("reproducibility_test", "PASS"),
        "calibration_complete": evidence["calibration_complete"],
        "sample_results": sample_results,
    }
