"""Settings from the environment. The names are the ones of the backend (backend/.env), so both read the same file."""

from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

# The limits of the app channel, the same as in backend/api/reports.py (POST /v1/reports)
MAX_PHOTO_BYTES = 15 * 1024 * 1024
MAX_TEXT_CHARS = 5000


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- Backend -----------------------------------------------------------
    backend_url: str = Field("http://backend:8000", description="The backend inside the compose network.")
    gateway_key: SecretStr = Field(
        description="Shared with the backend (GATEWAY_KEY), opens its entrance for the gateway."
    )
    # The app waits up to 120 s for its answer (BackendClient.swift). The gateway waits longer, never giving up first.
    backend_timeout_s: float = 150.0

    # --- Object storage: the raw bucket of the backend -----------------------
    storage_endpoint_url: str
    storage_access_key: SecretStr
    storage_secret_key: SecretStr
    storage_region: str = "us-east-1"
    storage_bucket_raw: str


@lru_cache
def get_settings() -> Settings:
    return Settings()
