from hashlib import sha256
from pathlib import Path

import pytest
from vtv_analysis import AudioAnalysis, SpeakerTurn, SpeechSegment, TranscriptSegment
from vtv_analysis_worker import AudioGoldenCase, AudioGoldenRun, run_audio_golden_dataset
from vtv_evaluation import (
    BenchmarkEvidence,
    BenchmarkPolicy,
    GoldenSample,
    TimedSpeakerLabel,
    evaluate_release,
)


class FakePipeline:
    def analyze(self, audio_uri: str, duration_seconds: float, language_hint: str | None):
        if audio_uri.endswith("broken.wav"):
            raise RuntimeError("model OOM")
        return AudioAnalysis(
            duration_seconds=duration_seconds,
            language=language_hint or "zh-CN",
            speech=(SpeechSegment(start_seconds=0, end_seconds=duration_seconds, confidence=1),),
            transcript=(
                TranscriptSegment(
                    start_seconds=0,
                    end_seconds=duration_seconds,
                    text="你好",
                    language="zh-CN",
                ),
            ),
            speakers=(
                SpeakerTurn(
                    start_seconds=0,
                    end_seconds=duration_seconds,
                    speaker_id="cluster:0",
                    confidence=0.5,
                ),
            ),
        )


def _case(path: Path, *, critical: bool = False) -> AudioGoldenCase:
    payload = path.read_bytes()
    return AudioGoldenCase(
        sample=GoldenSample(
            sample_id=path.stem,
            source_sha256=sha256(payload).hexdigest(),
            duration_seconds=2,
            critical=critical,
        ),
        audio_uri=path.resolve().as_uri(),
        reference_transcript="你好",
        reference_speakers=(TimedSpeakerLabel(0, 2, "actor-a"),),
        language_hint="zh-CN",
    )


def _run() -> AudioGoldenRun:
    return AudioGoldenRun(
        expected_model_state_version=3,
        dataset_key="audio-zh",
        dataset_release="golden@1",
        annotation_release="annotation@1",
        policy=BenchmarkPolicy(
            policy_key="audio-production",
            release="policy@1",
            minimum_sample_count=2,
            minimum_metric_scores={
                "transcript_accuracy": 0.9,
                "speaker_overlap_accuracy": 0.9,
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
            weights_sha256="c" * 64,
            runtime_fingerprint="L4|image-sha256:abc",
        ),
        cost_per_compute_second_usd=0.01,
    )


def test_runner_builds_api_payload_and_isolates_model_failure(tmp_path: Path) -> None:
    good = tmp_path / "good.wav"
    broken = tmp_path / "broken.wav"
    good.write_bytes(b"good-audio")
    broken.write_bytes(b"broken-audio")
    ticks = iter((0.0, 1.0, 2.0, 4.0))

    payload = run_audio_golden_dataset(
        cases=(_case(good), _case(broken, critical=True)),
        pipeline=FakePipeline(),
        run=_run(),
        clock=lambda: next(ticks),
        duration_probe=lambda path: 2,
    )

    assert payload.results[0].metric_scores["transcript_accuracy"] == 1
    assert payload.results[0].cost_usd == pytest.approx(0.01)
    assert payload.results[1].critical_failure is True
    assert payload.results[1].error_class == "RuntimeError"
    report = evaluate_release(
        model_key="AUDIO_ANALYSIS",
        model_release="audio@candidate",
        dataset=payload.dataset,
        policy=payload.policy,
        evidence=payload.evidence,
        results=payload.results,
    )
    assert report.approved is False
    assert "CRITICAL_SAMPLE_FAILURE" in report.failed_gates


def test_runner_rejects_changed_source_before_model_execution(tmp_path: Path) -> None:
    audio = tmp_path / "source.wav"
    audio.write_bytes(b"original")
    case = _case(audio)
    audio.write_bytes(b"changed")

    with pytest.raises(ValueError, match="SHA-256"):
        run_audio_golden_dataset(
            cases=(case,),
            pipeline=FakePipeline(),
            run=_run(),
            duration_probe=lambda path: 2,
        )


def test_runner_rejects_duration_drift(tmp_path: Path) -> None:
    audio = tmp_path / "source.wav"
    audio.write_bytes(b"audio")

    with pytest.raises(ValueError, match="duration mismatch"):
        run_audio_golden_dataset(
            cases=(_case(audio),),
            pipeline=FakePipeline(),
            run=_run(),
            duration_probe=lambda path: 2.2,
        )
