from functools import lru_cache
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="VTV_", env_file=".env", extra="ignore")

    analysis_adapter_mode: Literal["deterministic", "remote"] = "deterministic"
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
    model_timeout_seconds: float = 600


@lru_cache
def get_settings() -> Settings:
    return Settings()
