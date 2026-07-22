from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from time import perf_counter
from urllib.parse import unquote, urlparse

from vtv_audio import StemKind, StemSeparationAdapter
from vtv_evaluation import (
    BenchmarkEvidence,
    BenchmarkPolicy,
    GoldenDataset,
    GoldenSample,
    SampleResult,
    leakage_control,
    read_pcm_wav,
    reconstruction_accuracy,
    signal_fidelity,
)
from vtv_schemas.benchmarks import BenchmarkReleaseCreate


@dataclass(frozen=True, slots=True)
class StemGoldenCase:
    sample: GoldenSample
    source_uri: str
    reference_dialogue_uri: str
    reference_background_uri: str
    human_rejected: bool = False


@dataclass(frozen=True, slots=True)
class StemGoldenRun:
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


def run_stem_golden_dataset(
    *,
    cases: tuple[StemGoldenCase, ...],
    adapter: StemSeparationAdapter,
    run: StemGoldenRun,
    work_root: Path,
    clock: Callable[[], float] = perf_counter,
) -> BenchmarkReleaseCreate:
    if not cases:
        raise ValueError("Stem Golden Dataset cannot be empty")
    dataset = GoldenDataset(
        dataset_key=run.dataset_key,
        release=run.dataset_release,
        annotation_release=run.annotation_release,
        samples=tuple(case.sample for case in cases),
    )
    results: list[SampleResult] = []
    for case in cases:
        source, dialogue_reference, background_reference = _verified_case(case)
        source_signal = read_pcm_wav(source)
        dialogue_signal = read_pcm_wav(dialogue_reference)
        background_signal = read_pcm_wav(background_reference)
        # Reference incompatibility is a dataset error, not a model failure.
        reconstruction_accuracy(source_signal, dialogue_signal, background_signal)
        started = clock()
        try:
            separated = adapter.separate(
                source,
                work_root
                / case.sample.sample_id
                / sha256(adapter.model_release.encode()).hexdigest()[:16],
            )
            by_kind = {stem.kind: stem for stem in separated.stems}
            if StemKind.BACKGROUND not in by_kind:
                raise ValueError("Stem candidate did not produce BACKGROUND")
            predicted_dialogue = read_pcm_wav(by_kind[StemKind.DIALOGUE].path)
            predicted_background = read_pcm_wav(by_kind[StemKind.BACKGROUND].path)
            metrics = {
                "dialogue_fidelity": signal_fidelity(dialogue_signal, predicted_dialogue),
                "background_fidelity": signal_fidelity(
                    background_signal, predicted_background
                ),
                "dialogue_leakage_control": leakage_control(
                    dialogue_signal, predicted_background
                ),
                "reconstruction_accuracy": reconstruction_accuracy(
                    source_signal, predicted_dialogue, predicted_background
                ),
            }
            critical_failure = False
            error_class = None
        except Exception as exc:
            metrics = {
                "dialogue_fidelity": 0.0,
                "background_fidelity": 0.0,
                "dialogue_leakage_control": 0.0,
                "reconstruction_accuracy": 0.0,
            }
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


def _verified_case(case: StemGoldenCase) -> tuple[Path, Path, Path]:
    source = _local_path(case.source_uri)
    dialogue = _local_path(case.reference_dialogue_uri)
    background = _local_path(case.reference_background_uri)
    hashes = (_digest(dialogue), _digest(background))
    if _digest(source) != case.sample.source_sha256:
        raise ValueError(f"Golden sample {case.sample.sample_id} source SHA-256 mismatch")
    if hashes != case.sample.reference_sha256s:
        raise ValueError(f"Golden sample {case.sample.sample_id} reference SHA-256 mismatch")
    return source, dialogue, background


def _local_path(uri: str) -> Path:
    parsed = urlparse(uri)
    if parsed.scheme not in {"", "file"}:
        raise ValueError("Stem Golden runner requires local immutable files")
    path = Path(unquote(parsed.path if parsed.scheme else uri))
    if not path.is_file():
        raise FileNotFoundError(path)
    return path


def _digest(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(4 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()
