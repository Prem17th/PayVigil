from functools import lru_cache
import os
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(
            Path(__file__).resolve().parents[3] / ".env",
            Path(__file__).resolve().parents[2] / ".env",
        ),
        extra="ignore",
        populate_by_name=True,
    )

    database_url: SecretStr = SecretStr("")
    migration_database_url: SecretStr = SecretStr("")
    pgsslmode: str = "verify-full"
    pgsslrootcert: str = "system"
    supabase_url: str = ""
    supabase_publishable_key: SecretStr = Field(
        default=SecretStr(""),
        validation_alias=AliasChoices("SUPABASE_PUBLISHABLE_KEY", "SUPABASE_ANON_KEY"),
    )
    supabase_secret_key: SecretStr = Field(
        default=SecretStr(""),
        validation_alias=AliasChoices("SUPABASE_SECRET_KEY", "SUPABASE_SERVICE_ROLE_KEY"),
    )
    supabase_storage_bucket: str = "beforetransfer-evidence"
    cors_origins: str = ""
    app_env: str = "production"
    payment_approval_ttl_seconds: int = Field(default=600, ge=60, le=3600)
    payment_worker_lease_seconds: int = Field(default=60, ge=30, le=600)
    payment_reconcile_interval_seconds: int = Field(default=3, ge=1, le=60)

    @property
    def provider_url(self) -> str | None:
        """Only a configured origin; never follow provider redirects with keys."""
        value = self.supabase_url.strip().rstrip("/")
        try:
            parsed = urlsplit(value)
            local_http = (
                self.app_env == "test"
                and parsed.scheme == "http"
                and parsed.hostname in {"localhost", "127.0.0.1", "::1"}
            )
            if not (
                parsed.hostname
                and (parsed.scheme == "https" or local_http)
                and not parsed.username
                and not parsed.password
                and not parsed.path
                and not parsed.query
                and not parsed.fragment
            ):
                return None
            return value
        except ValueError:
            return None

    @property
    def auth_configured(self) -> bool:
        return bool(self.provider_url and self.supabase_publishable_key.get_secret_value())

    @property
    def database_configured(self) -> bool:
        return bool(self.database_url.get_secret_value().strip())

    @property
    def storage_configured(self) -> bool:
        return bool(
            self.auth_configured
            and self.supabase_secret_key.get_secret_value()
            and self.supabase_storage_bucket
        )

    @property
    def allowed_origins(self) -> list[str]:
        origins: list[str] = []
        for value in self.cors_origins.split(","):
            value = value.strip().rstrip("/")
            try:
                parsed = urlsplit(value)
                if (
                    (
                        parsed.scheme == "https"
                        or (
                            self.app_env == "test"
                            and parsed.scheme == "http"
                            and parsed.hostname in {"localhost", "127.0.0.1", "::1"}
                        )
                    )
                    and parsed.hostname
                    and not parsed.path
                    and not parsed.query
                    and not parsed.fragment
                    and not parsed.username
                    and not parsed.password
                ):
                    origins.append(value)
            except ValueError:
                continue
        return origins


@lru_cache
def get_settings() -> Settings:
    if os.environ.get("BEFORETRANSFER_DISABLE_DOTENV") == "1":
        return Settings(_env_file=None)
    return Settings()
