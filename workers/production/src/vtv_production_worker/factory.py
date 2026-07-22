from vtv_schemas.jobs import StageJob, StageResult

from .config import Settings, get_settings
from .runtime import (
    HttpxLipSyncTransport,
    HttpxTtsTransport,
    LipSyncEndpoint,
    PassthroughLipSyncAdapter,
    RemoteLipSyncAdapter,
    RemoteTtsAdapter,
    TtsEndpoint,
)
from .worker import ProductionWorker


def create_production_worker_for_job(
    job: StageJob, settings: Settings | None = None
) -> ProductionWorker:
    settings = settings or get_settings()
    if job.stage_type not in {"TTS_GENERATE", "LIPSYNC_GENERATE"}:
        raise ValueError(f"unsupported production stage: {job.stage_type}")
    if job.stage_type == "LIPSYNC_GENERATE":
        request = job.params.get("lipsync_request")
        decision = request.get("decision") if isinstance(request, dict) else None
        if isinstance(decision, dict) and decision.get("level") == "L0_NONE":
            return ProductionWorker(lipsync=PassthroughLipSyncAdapter())
    runtime = job.params.get("model_runtime")
    if not isinstance(runtime, dict):
        raise ValueError(f"{job.stage_type} requires a Registry-selected model runtime")
    config = runtime.get("config") if isinstance(runtime.get("config"), dict) else {}
    if job.stage_type == "LIPSYNC_GENERATE":
        if config.get("adapter_mode") != "remote_lipsync":
            raise ValueError(
                "LIPSYNC_GENERATE registry release must select remote_lipsync"
            )
        endpoint = LipSyncEndpoint(
            endpoint=str(runtime.get("endpoint") or ""),
            model_release=str(runtime.get("release") or ""),
            license_id=str(runtime.get("license_id") or ""),
            approved_for_automation=runtime.get("approved_for_automation") is True,
            bearer_token=(
                settings.lipsync_token.get_secret_value()
                if settings.lipsync_token
                else None
            ),
            timeout_seconds=settings.lipsync_timeout_seconds,
        )
        return ProductionWorker(
            lipsync=RemoteLipSyncAdapter(endpoint, HttpxLipSyncTransport())
        )
    if config.get("adapter_mode") != "remote_tts":
        raise ValueError("TTS_GENERATE registry release must select remote_tts")
    endpoint = TtsEndpoint(
        endpoint=str(runtime.get("endpoint") or ""),
        model_release=str(runtime.get("release") or ""),
        license_id=str(runtime.get("license_id") or ""),
        approved_for_automation=runtime.get("approved_for_automation") is True,
        bearer_token=(settings.tts_token.get_secret_value() if settings.tts_token else None),
        timeout_seconds=settings.tts_timeout_seconds,
    )
    return ProductionWorker(tts=RemoteTtsAdapter(endpoint, HttpxTtsTransport()))


def execute(job: StageJob) -> StageResult:
    return create_production_worker_for_job(job).execute(job)
