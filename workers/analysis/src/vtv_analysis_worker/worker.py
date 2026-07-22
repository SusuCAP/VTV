import json
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
from urllib.parse import unquote, urlparse

from vtv_analysis import (
    AudioAnalysis,
    AudioAnalysisPipeline,
    DeterministicAsr,
    DeterministicDiarization,
    DeterministicGeometryAdapter,
    DeterministicOcrAdapter,
    DeterministicPersonAdapter,
    DeterministicProjectSynthesizer,
    DeterministicSceneAdapter,
    DeterministicVad,
    ShotSpan,
    VisionAnalysis,
    VisionAnalysisPipeline,
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
    vision_pipeline: VisionAnalysisPipeline = field(
        default_factory=lambda: VisionAnalysisPipeline(
            people=DeterministicPersonAdapter(),
            scenes=DeterministicSceneAdapter(),
            ocr=DeterministicOcrAdapter(),
            geometry=DeterministicGeometryAdapter(),
        )
    )
    synthesizer: DeterministicProjectSynthesizer = field(
        default_factory=DeterministicProjectSynthesizer
    )

    def execute(self, job: StageJob) -> StageResult:
        if job.stage_type == "PROJECT_SYNTHESIS":
            return self._execute_project_synthesis(job)
        if job.stage_type == "VISION_ANALYSIS":
            return self._execute_vision(job)
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

    def _execute_project_synthesis(self, job: StageJob) -> StageResult:
        json_assets = [
            asset for asset in job.input_assets if asset.media_type == "application/json"
        ]
        if len(json_assets) != 2:
            raise ValueError("PROJECT_SYNTHESIS requires audio and vision JSON assets")

        audio: AudioAnalysis | None = None
        vision: VisionAnalysis | None = None
        upstream_releases: dict[str, str] = {}
        for asset in json_assets:
            payload = json.loads(_local_path(asset.uri).read_text(encoding="utf-8"))
            analysis = payload.get("analysis")
            if not isinstance(analysis, dict):
                raise ValueError("PROJECT_SYNTHESIS input is missing analysis object")
            releases = payload.get("model_releases", {})
            if not isinstance(releases, dict) or not all(
                isinstance(key, str) and isinstance(value, str) for key, value in releases.items()
            ):
                raise ValueError("PROJECT_SYNTHESIS input has invalid model releases")
            upstream_releases.update(releases)
            if "transcript" in analysis and "speakers" in analysis:
                if audio is not None:
                    raise ValueError("PROJECT_SYNTHESIS received duplicate audio analysis")
                audio = AudioAnalysis.model_validate(analysis)
            elif "people" in analysis and "geometry" in analysis:
                if vision is not None:
                    raise ValueError("PROJECT_SYNTHESIS received duplicate vision analysis")
                vision = VisionAnalysis.model_validate(analysis)
            else:
                raise ValueError("PROJECT_SYNTHESIS input analysis type is unknown")
        if audio is None or vision is None:
            raise ValueError("PROJECT_SYNTHESIS requires one audio and one vision analysis")

        source_locale = str(job.params.get("source_locale") or audio.language)
        target_locale = str(job.params.get("target_locale") or "en-US")
        synthesis = self.synthesizer.synthesize(
            project_id=str(job.project_id),
            episode_id=str(job.episode_id or "project-wide"),
            source_locale=source_locale,
            target_locale=target_locale,
            audio=audio,
            vision=vision,
        )
        releases = {**upstream_releases, "project_synthesis": self.synthesizer.model_release}
        output_directory = _local_path(job.output_prefix)
        output_directory.mkdir(parents=True, exist_ok=True)
        output = output_directory / "project-synthesis.json"
        output.write_text(
            json.dumps(
                {"synthesis": synthesis.model_dump(mode="json"), "model_releases": releases},
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
                        "characters": len(synthesis.bible.characters),
                        "locations": len(synthesis.bible.locations),
                        "continuity_snapshots": len(synthesis.continuity),
                        "model_releases": releases,
                    },
                )
            ],
            attempt_usage={"worker": "analysis", "local": True},
        )

    def _execute_vision(self, job: StageJob) -> StageResult:
        video_assets = [
            asset for asset in job.input_assets if asset.media_type.startswith("video/")
        ]
        json_assets = [
            asset for asset in job.input_assets if asset.media_type == "application/json"
        ]
        if len(video_assets) != 1 or len(json_assets) != 1:
            raise ValueError("VISION_ANALYSIS requires one video asset and one shots JSON asset")
        video = _local_path(video_assets[0].uri)
        shots_path = _local_path(json_assets[0].uri)
        probe = probe_media(video)
        raw_shots = json.loads(shots_path.read_text(encoding="utf-8"))["shots"]
        shots = tuple(
            ShotSpan(
                shot_no=int(item["shot_no"]),
                start_seconds=float(item["start_seconds"]),
                end_seconds=float(item["end_seconds"]),
            )
            for item in raw_shots
        )
        if not shots:
            raise ValueError("VISION_ANALYSIS shots list cannot be empty")
        if shots[0].start_seconds != 0 or any(
            current.end_seconds != following.start_seconds
            for current, following in zip(shots, shots[1:], strict=False)
        ):
            raise ValueError("VISION_ANALYSIS shots must form a continuous timeline from zero")
        if abs(shots[-1].end_seconds - probe.duration_seconds) > 0.05:
            raise ValueError("VISION_ANALYSIS shots do not cover media duration")

        analysis = self.vision_pipeline.analyze(
            video.resolve().as_uri(), probe.duration_seconds, shots
        )
        releases = {
            "people": self.vision_pipeline.people.model_release,
            "scenes": self.vision_pipeline.scenes.model_release,
            "ocr": self.vision_pipeline.ocr.model_release,
            "geometry": self.vision_pipeline.geometry.model_release,
        }
        output_directory = _local_path(job.output_prefix)
        output_directory.mkdir(parents=True, exist_ok=True)
        output = output_directory / "vision-analysis.json"
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
                        "shots": len(shots),
                        "people": len(analysis.people),
                        "scenes": len(analysis.scenes),
                        "ocr_regions": len(analysis.ocr),
                        "model_releases": releases,
                    },
                )
            ],
            attempt_usage={"worker": "analysis", "local": True},
        )


def execute(job: StageJob) -> StageResult:
    return AnalysisWorker().execute(job)
