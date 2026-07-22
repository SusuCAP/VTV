from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from time import perf_counter
from urllib.parse import unquote, urlparse

from vtv_analysis import AudioAnalysisPipeline
from vtv_evaluation import (
    BenchmarkEvidence,
    BenchmarkPolicy,
    GoldenDataset,
    GoldenSample,
    SampleResult,
    TimedSpeakerLabel,
    diarization_overlap_accuracy,
    transcript_accuracy,
)
from vtv_media import probe_media
from vtv_schemas.benchmarks import BenchmarkReleaseCreate


@dataclass(frozen=True, slots=True)
class AudioGoldenCase:
    sample: GoldenSample
    audio_uri: str
    reference_transcript: str
    reference_speakers: tuple[TimedSpeakerLabel, ...]
    language_hint: str | None = None
    human_rejected: bool = False


@dataclass(frozen=True, slots=True)
class AudioGoldenRun:
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


def run_audio_golden_dataset(
    *,
    cases: tuple[AudioGoldenCase, ...],
    pipeline: AudioAnalysisPipeline,
    run: AudioGoldenRun,
    clock: Callable[[], float] = perf_counter,
    duration_probe: Callable[[Path], float] | None = None,
) -> BenchmarkReleaseCreate:
    if not cases:
        raise ValueError("audio Golden Dataset cannot be empty")
    dataset = GoldenDataset(
        dataset_key=run.dataset_key,
        release=run.dataset_release,
        annotation_release=run.annotation_release,
        samples=tuple(case.sample for case in cases),
    )
    probe = duration_probe or _probe_duration
    results: list[SampleResult] = []
    for case in cases:
        path = _verified_source(case)
        measured_duration = probe(path)
        if abs(measured_duration - case.sample.duration_seconds) > 0.05:
            raise ValueError(
                f"Golden sample {case.sample.sample_id} duration mismatch: "
                f"declared {case.sample.duration_seconds}, actual {measured_duration}"
            )
        started = clock()
        try:
            analysis = pipeline.analyze(
                path.resolve().as_uri(), measured_duration, case.language_hint
            )
            hypothesis_text = " ".join(item.text for item in analysis.transcript)
            hypothesis_speakers = tuple(
                TimedSpeakerLabel(
                    start_seconds=item.start_seconds,
                    end_seconds=item.end_seconds,
                    speaker_id=item.speaker_id,
                )
                for item in analysis.speakers
            )
            metrics = {
                "transcript_accuracy": transcript_accuracy(
                    case.reference_transcript, hypothesis_text
                ),
                "speaker_overlap_accuracy": diarization_overlap_accuracy(
                    case.reference_speakers, hypothesis_speakers
                ),
            }
            critical_failure = False
            error_class = None
        except Exception as exc:
            metrics = {"transcript_accuracy": 0.0, "speaker_overlap_accuracy": 0.0}
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


def _verified_source(case: AudioGoldenCase) -> Path:
    parsed = urlparse(case.audio_uri)
    if parsed.scheme not in {"", "file"}:
        raise ValueError("Golden runner requires a local immutable source")
    path = Path(unquote(parsed.path if parsed.scheme else case.audio_uri))
    if not path.is_file():
        raise FileNotFoundError(path)
    digest = sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(4 * 1024 * 1024):
            digest.update(chunk)
    if digest.hexdigest() != case.sample.source_sha256:
        raise ValueError(f"Golden sample {case.sample.sample_id} SHA-256 mismatch")
    return path


def _probe_duration(path: Path) -> float:
    return probe_media(path, require_video=False).duration_seconds
