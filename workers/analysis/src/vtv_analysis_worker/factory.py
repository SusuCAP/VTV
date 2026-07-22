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
