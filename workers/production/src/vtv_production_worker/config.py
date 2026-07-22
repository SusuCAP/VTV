from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="VTV_", env_file=".env", extra="ignore")

    tts_token: SecretStr | None = None
    tts_timeout_seconds: float = 600


@lru_cache
def get_settings() -> Settings:
    return Settings()
