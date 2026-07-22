from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from time import perf_counter
from urllib.parse import unquote, urlparse

from vtv_analysis import NormalizedBox, ShotSpan, VisionAnalysis, VisionAnalysisPipeline
from vtv_evaluation import (
    BenchmarkEvidence,
    BenchmarkPolicy,
    EvaluationBox,
    GoldenDataset,
    GoldenSample,
    SampleResult,
    box_iou,
    label_f1,
    ocr_text_accuracy,
    temporal_iou,
)
from vtv_media import probe_media
from vtv_schemas.benchmarks import BenchmarkReleaseCreate


@dataclass(frozen=True, slots=True)
class VisionGoldenCase:
    sample: GoldenSample
    video_uri: str
    shots: tuple[ShotSpan, ...]
    reference: VisionAnalysis
    human_rejected: bool = False


@dataclass(frozen=True, slots=True)
class VisionGoldenRun:
    expected_model_state_version: int
    dataset_key: str
    dataset_release: str
    annotation_release: str
    policy: BenchmarkPolicy
    evidence: BenchmarkEvidence
    cost_per_compute_second_usd: float

    def __post_init__(self) -> None:
        if self.expected_model_state_version < 1:
            raise ValueError("expected model state version must be positive")
        if self.cost_per_compute_second_usd < 0:
            raise ValueError("compute cost cannot be negative")


def run_vision_golden_dataset(
    *,
    cases: tuple[VisionGoldenCase, ...],
    pipeline: VisionAnalysisPipeline,
    run: VisionGoldenRun,
    clock: Callable[[], float] = perf_counter,
    duration_probe: Callable[[Path], float] | None = None,
) -> BenchmarkReleaseCreate:
    if not cases:
        raise ValueError("vision Golden Dataset cannot be empty")
    dataset = GoldenDataset(
        dataset_key=run.dataset_key,
        release=run.dataset_release,
        annotation_release=run.annotation_release,
        samples=tuple(case.sample for case in cases),
    )
    probe = duration_probe or _probe_duration
    results: list[SampleResult] = []
    for case in cases:
        path = _verified_case(case)
        measured_duration = probe(path)
        if abs(measured_duration - case.sample.duration_seconds) > 0.05:
            raise ValueError(
                f"Golden sample {case.sample.sample_id} duration mismatch: "
                f"declared {case.sample.duration_seconds}, actual {measured_duration}"
            )
        started = clock()
        try:
            analysis = pipeline.analyze(
                path.resolve().as_uri(), measured_duration, case.shots
            )
            metrics = _metrics(case.reference, analysis)
            critical_failure = False
            error_class = None
        except Exception as exc:
            metrics = {name: 0.0 for name in _METRIC_NAMES}
            critical_failure = True
            error_class = type(exc).__name__
        latency = max(clock() - started, 1e-9)
        results.append(
            SampleResult(
                sample_id=case.sample.sample_id,
                metric_scores=metrics,
                critical_failure=critical_failure,
                human_rejected=case.human_rejected,
                latency_seconds=latency,
                cost_usd=latency * run.cost_per_compute_second_usd,
                output_duration_seconds=case.sample.duration_seconds,
                error_class=error_class,
            )
        )
    return BenchmarkReleaseCreate(
        expected_model_state_version=run.expected_model_state_version,
        dataset=dataset,
        policy=run.policy,
        evidence=run.evidence,
        results=tuple(results),
    )


_METRIC_NAMES = (
    "person_box_iou",
    "scene_temporal_iou",
    "scene_label_f1",
    "ocr_text_accuracy",
    "geometry_box_iou",
)


def vision_reference_sha256(reference: VisionAnalysis) -> str:
    payload = json.dumps(
        reference.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return sha256(payload.encode()).hexdigest()


def _metrics(reference: VisionAnalysis, hypothesis: VisionAnalysis) -> dict[str, float]:
    return {
        "person_box_iou": _mean_best_box(
            tuple(item.box for item in reference.people),
            tuple(item.box for item in hypothesis.people),
        ),
        "scene_temporal_iou": _mean_best_interval(
            tuple((item.start_seconds, item.end_seconds) for item in reference.scenes),
            tuple((item.start_seconds, item.end_seconds) for item in hypothesis.scenes),
        ),
        "scene_label_f1": label_f1(
            tuple(label for scene in reference.scenes for label in scene.labels),
            tuple(label for scene in hypothesis.scenes for label in scene.labels),
        ),
        "ocr_text_accuracy": ocr_text_accuracy(
            " ".join(item.text for item in reference.ocr),
            " ".join(item.text for item in hypothesis.ocr),
        ),
        "geometry_box_iou": _mean_best_box(
            tuple(box for item in reference.geometry for box in item.subject_boxes),
            tuple(box for item in hypothesis.geometry for box in item.subject_boxes),
        ),
    }


def _mean_best_box(
    reference: tuple[NormalizedBox, ...], hypothesis: tuple[NormalizedBox, ...]
) -> float:
    if not reference:
        return 1.0 if not hypothesis else 0.0
    if not hypothesis:
        return 0.0
    return sum(
        max(box_iou(_box(expected), _box(actual)) for actual in hypothesis)
        for expected in reference
    ) / len(reference)


def _mean_best_interval(
    reference: tuple[tuple[float, float], ...],
    hypothesis: tuple[tuple[float, float], ...],
) -> float:
    if not reference:
        return 1.0 if not hypothesis else 0.0
    if not hypothesis:
        return 0.0
    return sum(
        max(temporal_iou(expected, actual) for actual in hypothesis)
        for expected in reference
    ) / len(reference)


def _box(value: NormalizedBox) -> EvaluationBox:
    return EvaluationBox(x=value.x, y=value.y, width=value.width, height=value.height)


def _verified_case(case: VisionGoldenCase) -> Path:
    parsed = urlparse(case.video_uri)
    if parsed.scheme not in {"", "file"}:
        raise ValueError("vision Golden runner requires local immutable source")
    path = Path(unquote(parsed.path if parsed.scheme else case.video_uri))
    if not path.is_file():
        raise FileNotFoundError(path)
    if _file_sha256(path) != case.sample.source_sha256:
        raise ValueError(f"Golden sample {case.sample.sample_id} source SHA-256 mismatch")
    reference_hash = vision_reference_sha256(case.reference)
    if case.sample.reference_sha256s != (reference_hash,):
        raise ValueError(f"Golden sample {case.sample.sample_id} reference SHA-256 mismatch")
    return path


def _file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(4 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _probe_duration(path: Path) -> float:
    return probe_media(path, require_video=True).duration_seconds
