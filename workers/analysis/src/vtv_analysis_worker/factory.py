from vtv_schemas.jobs import StageJob

from .config import Settings, get_settings
from .runtime import (
    FallbackAudioAnalysisPipeline,
    FallbackVisionAnalysisPipeline,
    HttpxInferenceTransport,
    ModelEndpoint,
    RemoteAudioAnalysisPipeline,
    RemoteVisionAnalysisPipeline,
)
from .worker import AnalysisWorker


def create_analysis_worker(settings: Settings | None = None) -> AnalysisWorker:
    settings = settings or get_settings()
    deterministic = AnalysisWorker()
    if settings.analysis_adapter_mode == "deterministic":
        return deterministic
    transport = HttpxInferenceTransport()
    audio = RemoteAudioAnalysisPipeline(
        _endpoint(
            "audio",
            settings.audio_analysis_endpoint,
            settings.audio_analysis_release,
            settings.audio_analysis_license_id,
            settings.audio_analysis_approved,
            settings.audio_analysis_token.get_secret_value()
            if settings.audio_analysis_token
            else None,
            settings.model_timeout_seconds,
        ),
        transport,
    )
    vision = RemoteVisionAnalysisPipeline(
        _endpoint(
            "vision",
            settings.vision_analysis_endpoint,
            settings.vision_analysis_release,
            settings.vision_analysis_license_id,
            settings.vision_analysis_approved,
            settings.vision_analysis_token.get_secret_value()
            if settings.vision_analysis_token
            else None,
            settings.model_timeout_seconds,
        ),
        transport,
    )
    if settings.allow_model_fallback:
        audio = FallbackAudioAnalysisPipeline(audio, deterministic.pipeline)
        vision = FallbackVisionAnalysisPipeline(vision, deterministic.vision_pipeline)
    return AnalysisWorker(
        pipeline=audio,
        vision_pipeline=vision,
        synthesizer=deterministic.synthesizer,
    )


def create_analysis_worker_for_job(
    job: StageJob, settings: Settings | None = None
) -> AnalysisWorker:
    settings = settings or get_settings()
    runtime = job.params.get("model_runtime")
    if not isinstance(runtime, dict):
        return create_analysis_worker(settings)
    deterministic = AnalysisWorker()
    endpoint = ModelEndpoint(
        endpoint=str(runtime.get("endpoint") or ""),
        release=str(runtime.get("release") or ""),
        license_id=str(runtime.get("license_id") or ""),
        approved_for_automation=runtime.get("approved_for_automation") is True,
        bearer_token=(
            settings.audio_analysis_token.get_secret_value()
            if job.stage_type == "ASR_ALIGN" and settings.audio_analysis_token
            else settings.vision_analysis_token.get_secret_value()
            if job.stage_type == "VISION_ANALYSIS" and settings.vision_analysis_token
            else None
        ),
        timeout_seconds=settings.model_timeout_seconds,
    )
    transport = HttpxInferenceTransport()
    config = runtime.get("config") if isinstance(runtime.get("config"), dict) else {}
    allow_fallback = settings.allow_model_fallback and config.get("allow_fallback") is True
    if job.stage_type == "ASR_ALIGN":
        audio = RemoteAudioAnalysisPipeline(endpoint, transport)
        if allow_fallback:
            audio = FallbackAudioAnalysisPipeline(audio, deterministic.pipeline)
        return AnalysisWorker(
            pipeline=audio,
            vision_pipeline=deterministic.vision_pipeline,
            synthesizer=deterministic.synthesizer,
        )
    if job.stage_type == "VISION_ANALYSIS":
        vision = RemoteVisionAnalysisPipeline(endpoint, transport)
        if allow_fallback:
            vision = FallbackVisionAnalysisPipeline(vision, deterministic.vision_pipeline)
        return AnalysisWorker(
            pipeline=deterministic.pipeline,
            vision_pipeline=vision,
            synthesizer=deterministic.synthesizer,
        )
    raise ValueError(f"model runtime cannot be assigned to stage {job.stage_type}")


def _endpoint(
    kind: str,
    endpoint: str | None,
    release: str | None,
    license_id: str | None,
    approved: bool,
    token: str | None,
    timeout_seconds: float,
) -> ModelEndpoint:
    missing = [
        name
        for name, value in {
            "endpoint": endpoint,
            "release": release,
            "license_id": license_id,
        }.items()
        if not value
    ]
    if missing:
        raise ValueError(f"remote {kind} model configuration is missing: {', '.join(missing)}")
    return ModelEndpoint(
        endpoint=endpoint,
        release=release,
        license_id=license_id,
        approved_for_automation=approved,
        bearer_token=token,
        timeout_seconds=timeout_seconds,
    )
