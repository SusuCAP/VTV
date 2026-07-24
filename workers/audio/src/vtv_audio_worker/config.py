from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="VTV_", env_file=".env", extra="ignore")

    stem_adapter_mode: Literal["passthrough", "demucs"] = "demucs"
    demucs_model_name: str = "htdemucs"
    demucs_device: str = "cuda"
    demucs_release: str = "demucs-htdemucs@unapproved"


@lru_cache
def get_settings() -> Settings:
    return Settings()
