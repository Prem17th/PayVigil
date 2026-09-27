import pytest

from app.core.config import Settings
from app.core.database import database_url
from app.core.errors import AppError


def test_production_defaults_and_origins():
    settings = Settings(
        _env_file=None,
        cors_origins="https://app.example.com,http://untrusted.example.com,http://localhost:5173,*,https://app.example.com/path",
    )
    assert settings.app_env == "production"
    assert settings.allowed_origins == ["https://app.example.com"]
    assert settings.pgsslmode == "verify-full"


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost:54321",
        "https://name:password@example.com",
        "https://example.com/path",
        "https://example.com?token=secret",
    ],
)
def test_invalid_provider_origins_fail_closed(url):
    assert (
        Settings(
            _env_file=None, supabase_url=url, supabase_publishable_key="synthetic"
        ).auth_configured
        is False
    )


@pytest.mark.parametrize("mode", ["disable", "allow", "prefer", "require", "verify-ca"])
def test_production_rejects_tls_downgrade_in_uri(mode):
    settings = Settings(
        _env_file=None, database_url=f"postgresql://example.invalid/db?sslmode={mode}"
    )
    with pytest.raises(AppError):
        database_url(settings)


def test_production_rejects_tls_downgrade_in_environment():
    with pytest.raises(AppError):
        database_url(
            Settings(
                _env_file=None, database_url="postgresql://example.invalid/db", pgsslmode="require"
            )
        )


def test_production_database_uses_authenticated_tls_and_driver():
    result = database_url(Settings(_env_file=None, database_url="postgres://example.invalid/db"))
    assert result.drivername == "postgresql+psycopg"
    assert result.query["sslmode"] == "verify-full"
    assert result.query["sslrootcert"] == "system"


def test_migrations_require_separate_privileged_uri():
    with pytest.raises(AppError):
        database_url(
            Settings(
                _env_file=None,
                database_url="postgresql://example.invalid/db",
                migration_database_url="",
            ),
            migration=True,
        )
