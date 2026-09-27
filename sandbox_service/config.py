from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL, make_url


class SandboxSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SANDBOX_", extra="ignore")

    database_url: SecretStr = SecretStr("")
    migration_database_url: SecretStr = SecretStr("")
    api_key: SecretStr = SecretStr("")
    app_env: str = "production"
    pgsslmode: str = "verify-full"
    pgsslrootcert: str = "system"
    lost_response_delay_seconds: float = Field(default=10, ge=0.05, le=120)
    visibility_delay_seconds: float = Field(default=15, ge=0.05, le=300)


def database_url(settings: SandboxSettings, *, migration: bool = False) -> URL:
    raw = settings.migration_database_url if migration else settings.database_url
    try:
        url = make_url(raw.get_secret_value())
        if url.drivername not in {"postgres", "postgresql", "postgresql+psycopg"}:
            raise ValueError()
        mode = str(url.query.get("sslmode", settings.pgsslmode))
        if mode != "verify-full" and not (
            settings.app_env == "test"
            and url.host in {"127.0.0.1", "localhost", "::1"}
            and (url.database or "").endswith("_test")
            and mode == "disable"
        ):
            raise ValueError()
        query = dict(url.query)
        query["sslmode"] = mode
        if mode == "verify-full":
            query.setdefault("sslrootcert", settings.pgsslrootcert)
        query.setdefault("connect_timeout", "5")
        return url.set(drivername="postgresql+psycopg", query=query)
    except Exception:
        raise ValueError("Sandbox database configuration is missing or invalid.") from None


@lru_cache
def get_settings() -> SandboxSettings:
    return SandboxSettings()
