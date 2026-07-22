import json
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
from urllib.parse import unquote, urlparse

from vtv_analysis import (
    AudioAnalysisPipeline,
    DeterministicAsr,
    DeterministicDiarization,
    DeterministicVad,
)
from vtv_media import extract_audio, probe_media
from vtv_schemas.jobs import AssetRef, StageJob, StageResult, VariantResult


def _local_path(uri: str) -> Path:
    parsed = urlparse(uri)
    if parsed.scheme not in {"", "file"}:
        raise ValueError(f"analysis worker local mode cannot resolve URI scheme: {parsed.scheme}")
    return Path(unquote(parsed.path if parsed.scheme else uri))


def _asset(path: Path, media_type: str) -> AssetRef:
    digest = sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(4 * 1024 * 1024):
            digest.update(chunk)
    return AssetRef(
        uri=path.resolve().as_uri(),
        sha256=digest.hexdigest(),
        media_type=media_type,
        size_bytes=path.stat().st_size,
    )


@dataclass(frozen=True, slots=True)
class AnalysisWorker:
    pipeline: AudioAnalysisPipeline = field(
        default_factory=lambda: AudioAnalysisPipeline(
            vad=DeterministicVad(),
            asr=DeterministicAsr(),
            diarization=DeterministicDiarization(),
        )
    )

    def execute(self, job: StageJob) -> StageResult:
        if job.stage_type != "ASR_ALIGN":
            raise ValueError(f"unsupported analysis stage: {job.stage_type}")
        if not job.input_assets:
            raise ValueError("ASR_ALIGN requires at least one input asset")

        source = _local_path(job.input_assets[0].uri)
        output_directory = _local_path(job.output_prefix)
        output_directory.mkdir(parents=True, exist_ok=True)
        probe = probe_media(source, require_video=False)
        if not probe.audio_streams:
            raise ValueError("ASR_ALIGN input does not contain an audio stream")

        audio = source
        if probe.video_streams or source.suffix.lower() != ".wav":
            audio = extract_audio(source, output_directory / "analysis-input.wav")
        analysis = self.pipeline.analyze(
            audio.resolve().as_uri(),
            probe.duration_seconds,
            str(job.params["language_hint"]) if job.params.get("language_hint") else None,
        )
        releases = {
            "vad": self.pipeline.vad.model_release,
            "asr_align": self.pipeline.asr.model_release,
            "diarization": self.pipeline.diarization.model_release,
        }
        output = output_directory / "audio-analysis.json"
        output.write_text(
            json.dumps(
                {"analysis": analysis.model_dump(mode="json"), "model_releases": releases},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return StageResult(
            stage_run_id=job.stage_run_id,
            stage_attempt_id=job.stage_attempt_id,
            status="OUTPUT_READY",
            variants=[
                VariantResult(
                    variant_no=1,
                    output_assets=[_asset(output, "application/json")],
                    raw_metrics={
                        "worker": "analysis",
                        "stage_type": job.stage_type,
                        "speech_segments": len(analysis.speech),
                        "transcript_segments": len(analysis.transcript),
                        "speaker_turns": len(analysis.speakers),
                        "model_releases": releases,
                    },
                )
            ],
            attempt_usage={"worker": "analysis", "local": True},
        )


def execute(job: StageJob) -> StageResult:
    return AnalysisWorker().execute(job)
