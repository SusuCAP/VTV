from functools import lru_cache
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="VTV_", env_file=".env", extra="ignore")

    # Production requires an explicitly configured remote or local model stack.
    # Deterministic adapters remain available only when deliberately selected
    # by isolated tests.
    analysis_adapter_mode: Literal["deterministic", "local_models", "remote"] = "remote"
    allow_model_fallback: bool = False
    audio_analysis_endpoint: str | None = None
    audio_analysis_release: str | None = None
    audio_analysis_license_id: str | None = None
    audio_analysis_approved: bool = False
    audio_analysis_token: SecretStr | None = None
    vision_analysis_endpoint: str | None = None
    vision_analysis_release: str | None = None
    vision_analysis_license_id: str | None = None
    vision_analysis_approved: bool = False
    vision_analysis_token: SecretStr | None = None
    project_synthesis_endpoint: str | None = None
    project_synthesis_release: str | None = None
    project_synthesis_license_id: str | None = None
    project_synthesis_approved: bool = False
    project_synthesis_token: SecretStr | None = None
    model_timeout_seconds: float = 600
    whisper_model_name: str = "large-v3"
    whisper_device: str = "cuda"
    whisper_compute_type: str = "float16"
    whisper_release: str = "whisper-large-v3@unapproved"
    vad_release: str = "silero-vad@faster-whisper-unapproved"
    pyannote_model_name: str = "pyannote/speaker-diarization-community-1"
    pyannote_token_env: str = "HF_TOKEN"
    pyannote_device: str = "cuda"
    pyannote_release: str = "pyannote-community-1@unapproved"
    qwen_vision_model_name: str = "Qwen/Qwen3-VL-8B-Instruct"
    qwen_vision_release: str = "qwen3-vl-8b-instruct@unapproved"
    qwen_vision_max_new_tokens: int = 8192


@lru_cache
def get_settings() -> Settings:
    return Settings()
