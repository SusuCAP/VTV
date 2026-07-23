from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="VTV_", env_file=".env", extra="ignore")

    environment: str = "local"
    api_title: str = "VTV Control API"
    api_version: str = "0.1.0"
    database_url: str | None = None
    s3_endpoint: str | None = None
    s3_region: str = "us-east-1"
    s3_access_key: str | None = None
    s3_secret_key: str | None = None
    s3_bucket: str = "vtv-local"
    # Optional API key for Bearer token auth (empty string = auth disabled, local dev only)
    api_key: str = ""
    # HuggingFace token for gated models
    hf_token: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
