"""Runtime configuration, read from environment variables (prefix ``GATEWAY_``)."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="GATEWAY_", env_file=".env", extra="ignore")

    # --- General -----------------------------------------------------------
    tenant: str = Field("pilot", description="Tenant (municipality) assigned to incoming reports.")
    api_keys: list[SecretStr] = Field(
        default_factory=list,
        description="Accepted values for the X-API-Key header. Empty list disables the check (local dev only).",
    )

    # --- Database ----------------------------------------------------------
    database_url: str = Field(
        "sqlite:///./gateway.db",
        description="SQLAlchemy URL. Supabase: postgresql+psycopg://user:pass@host:5432/postgres",
    )

    # --- Storage -----------------------------------------------------------
    storage_backend: Literal["local", "s3"] = "local"
    storage_local_root: str = "./data/storage"
    storage_bucket_anonymized: str = "reports-anonymized"
    storage_bucket_raw: str = Field(
        "reports-raw",
        description="Private bucket for photos that still need the server-side privacy check.",
    )
    s3_endpoint_url: str | None = Field(
        None, description="S3-compatible endpoint, e.g. https://<project>.supabase.co/storage/v1/s3"
    )
    s3_region: str = "eu-central-1"
    s3_access_key_id: SecretStr | None = None
    s3_secret_access_key: SecretStr | None = None

    # --- Input limits ------------------------------------------------------
    max_photo_bytes: int = 15 * 1024 * 1024
    max_photo_edge_px: int = 2000
    max_photos_per_report: int = 3
    max_text_chars: int = 5000
    max_location_accuracy_m: float = Field(
        200.0, description="Reports from the app with a worse GPS accuracy are rejected."
    )

    # --- Email channel (IMAP) ---------------------------------------------
    imap_host: str | None = None
    imap_port: int = 993
    imap_username: str | None = None
    imap_password: SecretStr | None = None
    imap_inbox: str = "INBOX"
    imap_folder_processed: str = "processed"
    imap_folder_ignored: str = "ignored"
    imap_folder_failed: str = "failed"
    imap_poll_interval_s: int = 60


@lru_cache
def get_settings() -> Settings:
    return Settings()
