import struct
import wave
from hashlib import sha256
from pathlib import Path

import pytest
from vtv_audio import StemKind, StemOutput, StemSeparationResult
from vtv_audio_worker import StemGoldenCase, StemGoldenRun, run_stem_golden_dataset
from vtv_evaluation import BenchmarkEvidence, BenchmarkPolicy, GoldenSample, evaluate_release


def _wav(path: Path, values: tuple[float, ...]) -> Path:
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(8000)
        handle.writeframes(
            struct.pack(f"<{len(values)}h", *(round(value * 32767) for value in values))
        )
    return path


def _digest(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


class FakeAdapter:
    model_release = "stem-model@1"

    def __init__(self, dialogue: Path, background: Path, *, omit_background: bool = False):
        self.dialogue = dialogue
        self.background = background
        self.omit_background = omit_background

    def separate(self, source: Path, output_directory: Path) -> StemSeparationResult:
        stems = [StemOutput(
            kind=StemKind.DIALOGUE,
            path=self.dialogue,
            duration_seconds=0.0005,
            channels=1,
            sample_rate=8000,
        )]
        if not self.omit_background:
            stems.append(StemOutput(
                kind=StemKind.BACKGROUND,
                path=self.background,
                duration_seconds=0.0005,
                channels=1,
                sample_rate=8000,
            ))
        return StemSeparationResult(
            source_duration_seconds=0.0005,
            stems=tuple(stems),
            model_release=self.model_release,
        )


def _fixture(tmp_path: Path) -> tuple[StemGoldenCase, Path, Path]:
    dialogue_values = (0.4, -0.4, 0.4, -0.4)
    background_values = (0.1, 0.1, -0.1, -0.1)
    dialogue = _wav(tmp_path / "dialogue.wav", dialogue_values)
    background = _wav(tmp_path / "background.wav", background_values)
    source = _wav(
        tmp_path / "source.wav",
        tuple(
            left + right
            for left, right in zip(dialogue_values, background_values, strict=True)
        ),
    )
    sample = GoldenSample(
        sample_id="stem-1",
        source_sha256=_digest(source),
        reference_sha256s=(_digest(dialogue), _digest(background)),
        duration_seconds=0.0005,
        critical=True,
    )
    return (
        StemGoldenCase(
            sample=sample,
            source_uri=source.resolve().as_uri(),
            reference_dialogue_uri=dialogue.resolve().as_uri(),
            reference_background_uri=background.resolve().as_uri(),
        ),
        dialogue,
        background,
    )


def _run() -> StemGoldenRun:
    return StemGoldenRun(
        expected_model_state_version=3,
        dataset_key="stem-golden",
        dataset_release="golden@1",
        annotation_release="references@1",
        policy=BenchmarkPolicy(
            policy_key="stem-production",
            release="policy@1",
            minimum_sample_count=1,
            minimum_metric_scores={
                "dialogue_fidelity": 0.99,
                "background_fidelity": 0.99,
                "dialogue_leakage_control": 0.99,
                "reconstruction_accuracy": 0.99,
            },
            maximum_critical_failure_rate=0,
            maximum_human_reject_rate=0,
            maximum_cost_per_passed_second=100,
            maximum_p95_latency_seconds=5,
        ),
        evidence=BenchmarkEvidence(
            technical_access_gate="PASS",
            rollback_test="PASS",
            reproducibility_test="PASS",
            calibration_complete=True,
            weights_sha256="d" * 64,
            runtime_fingerprint="L4|demucs-4.1.0",
        ),
        cost_per_compute_second_usd=0.01,
    )


def test_stem_runner_builds_an_approved_benchmark_payload(tmp_path: Path) -> None:
    case, dialogue, background = _fixture(tmp_path)
    ticks = iter((0.0, 1.0))

    payload = run_stem_golden_dataset(
        cases=(case,),
        adapter=FakeAdapter(dialogue, background),
        run=_run(),
        work_root=tmp_path / "work",
        clock=lambda: next(ticks),
    )

    report = evaluate_release(
        model_key="AUDIO_STEM_SEPARATION",
        model_release="stem-model@1",
        dataset=payload.dataset,
        policy=payload.policy,
        evidence=payload.evidence,
        results=payload.results,
    )
    assert report.approved is True
    assert payload.results[0].cost_usd == pytest.approx(0.01)


def test_stem_runner_isolates_missing_background_as_model_failure(tmp_path: Path) -> None:
    case, dialogue, background = _fixture(tmp_path)
    ticks = iter((0.0, 1.0))

    payload = run_stem_golden_dataset(
        cases=(case,),
        adapter=FakeAdapter(dialogue, background, omit_background=True),
        run=_run(),
        work_root=tmp_path / "work",
        clock=lambda: next(ticks),
    )

    assert payload.results[0].critical_failure is True
    assert payload.results[0].error_class == "ValueError"


def test_stem_runner_rejects_reference_drift_before_inference(tmp_path: Path) -> None:
    case, dialogue, background = _fixture(tmp_path)
    background.write_bytes(b"changed")

    with pytest.raises(ValueError, match="reference SHA-256"):
        run_stem_golden_dataset(
            cases=(case,),
            adapter=FakeAdapter(dialogue, background),
            run=_run(),
            work_root=tmp_path / "work",
        )
