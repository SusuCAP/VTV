from __future__ import annotations

from math import ceil, sqrt
from statistics import fmean, stdev

from .contracts import (
    BenchmarkEvidence,
    BenchmarkPolicy,
    BenchmarkReport,
    GoldenDataset,
    MetricAggregate,
    SampleResult,
)


def _lower_confidence_bound(values: list[float], z: float) -> float:
    mean = fmean(values)
    if len(values) == 1:
        return mean
    margin = z * stdev(values) / sqrt(len(values))
    return max(0.0, min(1.0, mean - margin))


def _p95(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[max(0, ceil(0.95 * len(ordered)) - 1)]


def evaluate_release(
    *,
    model_key: str,
    model_release: str,
    dataset: GoldenDataset,
    policy: BenchmarkPolicy,
    evidence: BenchmarkEvidence,
    results: tuple[SampleResult, ...],
) -> BenchmarkReport:
    expected_ids = {sample.sample_id for sample in dataset.samples}
    actual_ids = [result.sample_id for result in results]
    if len(actual_ids) != len(set(actual_ids)):
        raise ValueError("benchmark results contain duplicate sample IDs")
    if set(actual_ids) != expected_ids:
        missing = sorted(expected_ids - set(actual_ids))
        unexpected = sorted(set(actual_ids) - expected_ids)
        raise ValueError(f"benchmark sample mismatch: missing={missing}, unexpected={unexpected}")

    failed: list[str] = []
    if evidence.technical_access_gate != "PASS":
        failed.append("TECHNICAL_ACCESS_GATE")
    if evidence.rollback_test != "PASS":
        failed.append("ROLLBACK_TEST")
    if evidence.reproducibility_test != "PASS":
        failed.append("REPRODUCIBILITY_TEST")
    if not evidence.calibration_complete:
        failed.append("CALIBRATION_INCOMPLETE")
    if len(results) < policy.minimum_sample_count:
        failed.append("INSUFFICIENT_SAMPLE_COUNT")

    sample_count = len(results)
    critical_failure_rate = sum(item.critical_failure for item in results) / sample_count
    human_reject_rate = sum(item.human_rejected for item in results) / sample_count
    if critical_failure_rate > policy.maximum_critical_failure_rate:
        failed.append("CRITICAL_FAILURE_RATE")
    if human_reject_rate > policy.maximum_human_reject_rate:
        failed.append("HUMAN_REJECT_RATE")
    sample_by_id = {sample.sample_id: sample for sample in dataset.samples}
    if any(item.critical_failure and sample_by_id[item.sample_id].critical for item in results):
        failed.append("CRITICAL_SAMPLE_FAILURE")

    passed = [item for item in results if not item.critical_failure and not item.human_rejected]
    passed_seconds = sum(item.output_duration_seconds for item in passed)
    cost_per_second = (
        sum(item.cost_usd for item in results) / passed_seconds if passed_seconds else None
    )
    if cost_per_second is None or cost_per_second > policy.maximum_cost_per_passed_second:
        failed.append("COST_PER_PASSED_OUTPUT_SECOND")

    p95_latency = _p95([item.latency_seconds for item in results])
    if p95_latency > policy.maximum_p95_latency_seconds:
        failed.append("P95_LATENCY")

    metrics: dict[str, MetricAggregate] = {}
    for metric_name, threshold in sorted(policy.minimum_metric_scores.items()):
        values = [
            item.metric_scores[metric_name]
            for item in results
            if metric_name in item.metric_scores
        ]
        if len(values) != sample_count:
            failed.append(f"METRIC_MISSING:{metric_name}")
            continue
        aggregate = MetricAggregate(
            mean=fmean(values),
            confidence_lower_bound=_lower_confidence_bound(values, policy.confidence_z),
            sample_count=len(values),
        )
        metrics[metric_name] = aggregate
        if aggregate.confidence_lower_bound < threshold:
            failed.append(f"METRIC_BELOW_THRESHOLD:{metric_name}")

    unique_failed = tuple(dict.fromkeys(failed))
    return BenchmarkReport(
        model_key=model_key,
        model_release=model_release,
        dataset_fingerprint=dataset.fingerprint,
        policy_fingerprint=policy.fingerprint,
        sample_count=sample_count,
        critical_failure_rate=critical_failure_rate,
        human_reject_rate=human_reject_rate,
        cost_per_passed_output_second=cost_per_second,
        p95_latency_seconds=p95_latency,
        metrics=metrics,
        approved=not unique_failed,
        failed_gates=unique_failed,
    )
