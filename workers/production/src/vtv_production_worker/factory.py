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

    # L0 lipsync: always passthrough regardless of model_runtime
    if job.stage_type == "LIPSYNC_GENERATE":
        request = job.params.get("lipsync_request")
        decision = request.get("decision") if isinstance(request, dict) else None
        if isinstance(decision, dict) and decision.get("level") == "L0_NONE":
            return ProductionWorker(lipsync=PassthroughLipSyncAdapter())

    runtime = job.params.get("model_runtime")
    if not isinstance(runtime, dict):
        raise ValueError(f"{job.stage_type} requires a Registry-selected model runtime")

    # Support both flat style (scheduler-injected: runtime["adapter_mode"])
    # and nested style (registry release: runtime["config"]["adapter_mode"]).
    _config = runtime.get("config") if isinstance(runtime.get("config"), dict) else {}
    adapter_mode = runtime.get("adapter_mode") or _config.get("adapter_mode", "")

    # ── Lipsync dispatch ──────────────────────────────────────────────────────
    if job.stage_type == "LIPSYNC_GENERATE":
        if adapter_mode == "latentsync":
            from vtv_production.latentsync_adapter import LatentSync16Adapter
            return ProductionWorker(lipsync=LatentSync16Adapter())
        if adapter_mode == "passthrough":
            return ProductionWorker(lipsync=PassthroughLipSyncAdapter())
        if adapter_mode != "remote_lipsync":
            raise ValueError(
                f"LIPSYNC_GENERATE: unsupported adapter_mode '{adapter_mode}'. "
                "Use 'latentsync', 'passthrough', or 'remote_lipsync'."
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
        return ProductionWorker(lipsync=RemoteLipSyncAdapter(endpoint, HttpxLipSyncTransport()))

    # ── TTS dispatch ──────────────────────────────────────────────────────────
    if adapter_mode == "cosyvoice3":
        from vtv_production.cosyvoice3_adapter import CosyVoice3Adapter
        return ProductionWorker(tts=CosyVoice3Adapter())
    if adapter_mode == "voxcpm2":
        from vtv_production.voxcpm2_adapter import VoxCPM2Adapter
        return ProductionWorker(tts=VoxCPM2Adapter())
    if adapter_mode == "fish_audio":
        from vtv_production.fish_audio_adapter import FishAudioS2ProAdapter
        return ProductionWorker(tts=FishAudioS2ProAdapter())
    if adapter_mode == "indextts2":
        from vtv_production.indextts2_adapter import IndexTTS2Adapter
        return ProductionWorker(tts=IndexTTS2Adapter())
    if adapter_mode == "passthrough":
        raise ValueError(
            "TTS_GENERATE passthrough is not supported. "
            "Set VTV_TTS_ADAPTER_MODE to cosyvoice3, voxcpm2, fish_audio, or remote_tts."
        )
    if adapter_mode != "remote_tts":
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
