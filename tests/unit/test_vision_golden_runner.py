from hashlib import sha256
from pathlib import Path

import pytest
from vtv_analysis import (
    DeterministicGeometryAdapter,
    DeterministicOcrAdapter,
    DeterministicPersonAdapter,
    DeterministicSceneAdapter,
    ShotSpan,
    VisionAnalysisPipeline,
)
from vtv_analysis_worker import (
    VisionGoldenCase,
    VisionGoldenRun,
    run_vision_golden_dataset,
    vision_reference_sha256,
)
from vtv_evaluation import BenchmarkEvidence, BenchmarkPolicy, GoldenSample


def _pipeline() -> VisionAnalysisPipeline:
    return VisionAnalysisPipeline(
        people=DeterministicPersonAdapter(),
        scenes=DeterministicSceneAdapter(),
        ocr=DeterministicOcrAdapter(),
        geometry=DeterministicGeometryAdapter(),
    )


def _case(path: Path) -> VisionGoldenCase:
    shots = (ShotSpan(shot_no=1, start_seconds=0, end_seconds=2),)
    reference = _pipeline().analyze(path.resolve().as_uri(), 2, shots)
    return VisionGoldenCase(
        sample=GoldenSample(
            sample_id=path.stem,
            source_sha256=sha256(path.read_bytes()).hexdigest(),
            reference_sha256s=(vision_reference_sha256(reference),),
            duration_seconds=2,
        ),
        video_uri=path.resolve().as_uri(),
        shots=shots,
        reference=reference,
    )


def _run() -> VisionGoldenRun:
    return VisionGoldenRun(
        expected_model_state_version=2,
        dataset_key="vision-shots",
        dataset_release="golden@1",
        annotation_release="annotation@1",
        policy=BenchmarkPolicy(
            policy_key="vision-production",
            release="policy@1",
            minimum_sample_count=1,
            minimum_metric_scores={
                "person_box_iou": 0.8,
                "scene_temporal_iou": 0.8,
                "scene_label_f1": 0.8,
                "ocr_text_accuracy": 0.8,
                "geometry_box_iou": 0.8,
            },
            maximum_critical_failure_rate=0,
            maximum_human_reject_rate=0,
            maximum_cost_per_passed_second=0.1,
            maximum_p95_latency_seconds=5,
        ),
        evidence=BenchmarkEvidence(
            technical_access_gate="PASS",
            rollback_test="PASS",
            reproducibility_test="PASS",
            calibration_complete=True,
            weights_sha256="d" * 64,
            runtime_fingerprint="L4|vision-image-sha256:abc",
        ),
        cost_per_compute_second_usd=0.01,
    )


def test_vision_runner_builds_complete_benchmark_payload(tmp_path: Path) -> None:
    video = tmp_path / "golden.mp4"
    video.write_bytes(b"video")
    ticks = iter((0.0, 1.5))

    payload = run_vision_golden_dataset(
        cases=(_case(video),),
        pipeline=_pipeline(),
        run=_run(),
        clock=lambda: next(ticks),
        duration_probe=lambda path: 2,
    )

    assert set(payload.results[0].metric_scores) == {
        "person_box_iou",
        "scene_temporal_iou",
        "scene_label_f1",
        "ocr_text_accuracy",
        "geometry_box_iou",
    }
    assert all(score == 1 for score in payload.results[0].metric_scores.values())
    assert payload.results[0].cost_usd == pytest.approx(0.015)


def test_vision_runner_rejects_annotation_hash_drift(tmp_path: Path) -> None:
    video = tmp_path / "golden.mp4"
    video.write_bytes(b"video")
    case = _case(video)
    changed = case.reference.model_copy(update={"duration_seconds": 2.1})

    with pytest.raises(ValueError, match="reference SHA-256"):
        run_vision_golden_dataset(
            cases=(VisionGoldenCase(case.sample, case.video_uri, case.shots, changed),),
            pipeline=_pipeline(),
            run=_run(),
            duration_probe=lambda path: 2,
        )
