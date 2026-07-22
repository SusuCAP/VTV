from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="VTV_", env_file=".env", extra="ignore")

    environment: str = "local"
    api_title: str = "VTV Control API"
    api_version: str = "0.1.0"
    database_url: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
