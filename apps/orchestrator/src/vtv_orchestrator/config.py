from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class ModelRuntimeSettings(BaseSettings):
    """Per-stage adapter mode selection.

    Each field maps to the ``adapter_mode`` key injected into ``StageJob.params["model_runtime"]``.
    Production defaults require a registry-selected real runtime. Explicit
    deterministic/passthrough modes are reserved for isolated contract tests.
    Override via environment variables (e.g. ``VTV_ASR_ADAPTER_MODE=local_models``) or
    by loading a configs/environments/*.yaml file before starting the orchestrator.
    """

    # No env_file — reads only actual process environment variables so that
    # standalone test instantiation (ModelRuntimeSettings()) uses clean defaults.
    # Production: start.sh does `source .env` which exports vars into the process.
    model_config = SettingsConfigDict(env_prefix="VTV_", extra="ignore")

    # ASR / VAD  ── "deterministic" | "local_models" | "remote"
    asr_adapter_mode: str = "remote"
    # Vision analysis ── "deterministic" | "qwen3_vl" | "remote"
    vision_adapter_mode: str = "remote"
    # Project-wide evidence-backed localization synthesis
    project_synthesis_adapter_mode: str = "remote"
    # Segmentation ── "passthrough" | "sam3" | "remote"
    segmentation_adapter_mode: str = "sam3"
    # Visual generation (char/bg replace, full regen) ── "passthrough" | "wan_animate" | "remote"
    visual_generation_adapter_mode: str = "wan_animate"
    # TTS synthesis ── "passthrough" | "cosyvoice3" | "remote_tts"
    tts_adapter_mode: str = "remote_tts"
    # Lipsync ── "passthrough" | "latentsync" | "remote_lipsync"
    lipsync_adapter_mode: str = "remote_lipsync"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="VTV_", env_file=".env", extra="ignore")

    environment: str = "local"
    s3_endpoint: str | None = None
    s3_region: str = "us-east-1"
    s3_access_key: str | None = None
    s3_secret_key: str | None = None
    s3_bucket: str = "vtv-local"
    # HuggingFace token for gated models (pyannote, etc.)
    hf_token: str | None = None
    # Stable identity exposed by the configured C2PA KMS/HSM signer process.
    c2pa_signer_id: str | None = None

    # Nested model-runtime settings (read from same env prefix)
    model_runtime: ModelRuntimeSettings = ModelRuntimeSettings()


@lru_cache
def get_settings() -> Settings:
    return Settings()


def model_runtime_for_stage(stage_type: str, settings: Settings | None = None) -> dict[str, str]:
    """Return the ``model_runtime`` dict to inject into ``StageJob.params`` for *stage_type*.

    Workers read ``job.params.get("model_runtime", {})`` and dispatch to the correct adapter.
    Returns an empty dict for stage types that do not use a pluggable model adapter.
    """
    if settings is None:
        settings = get_settings()
    rt = settings.model_runtime

    _map: dict[str, dict[str, str]] = {
        "ASR_ALIGN": {"adapter_mode": rt.asr_adapter_mode},
        "VISION_ANALYSIS": {"adapter_mode": rt.vision_adapter_mode},
        "PROJECT_SYNTHESIS": {"adapter_mode": rt.project_synthesis_adapter_mode},
        "VISUAL_CHARACTER_REPLACE": {
            "adapter_mode": rt.visual_generation_adapter_mode,
            "segmentation_adapter_mode": rt.segmentation_adapter_mode,
        },
        "VISUAL_BACKGROUND_REPLACE": {
            "adapter_mode": rt.visual_generation_adapter_mode,
            "segmentation_adapter_mode": rt.segmentation_adapter_mode,
        },
        "VISUAL_JOINT_REPLACE": {
            "adapter_mode": rt.visual_generation_adapter_mode,
            "segmentation_adapter_mode": rt.segmentation_adapter_mode,
        },
        "VISUAL_FULL_REGEN": {"adapter_mode": rt.visual_generation_adapter_mode},
        "VISUAL_SUBTITLE_CLEAN": {"adapter_mode": rt.visual_generation_adapter_mode},
        "TTS_GENERATE": {"adapter_mode": rt.tts_adapter_mode},
        "LIPSYNC_GENERATE": {"adapter_mode": rt.lipsync_adapter_mode},
    }
    return _map.get(stage_type, {})
