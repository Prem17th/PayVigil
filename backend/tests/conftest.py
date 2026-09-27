from types import SimpleNamespace
from uuid import UUID

import httpx
import pytest

from app.core.config import Settings, get_settings
from app.core.database import get_session
from app.main import create_app
from app.core.providers import get_provider_client


USER_ID = UUID("10000000-0000-4000-8000-000000000001")
TENANT_ID = UUID("20000000-0000-4000-8000-000000000001")


@pytest.fixture(autouse=True)
def isolated_settings_environment(monkeypatch):
    # A test invocation must not inherit real provider credentials or change
    # production-default assertions because a migration used APP_ENV=test.
    for name in (
        "APP_ENV",
        "DATABASE_URL",
        "MIGRATION_DATABASE_URL",
        "PGSSLMODE",
        "PGSSLROOTCERT",
        "SUPABASE_URL",
        "SUPABASE_PUBLISHABLE_KEY",
        "SUPABASE_ANON_KEY",
        "SUPABASE_SECRET_KEY",
        "SUPABASE_SERVICE_ROLE_KEY",
        "SUPABASE_STORAGE_BUCKET",
        "CORS_ORIGINS",
        "OPENAI_API_KEY",
        "OPENAI_MODEL",
        "BREETH_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)
    get_settings.cache_clear()
    from app.evidence.config import get_evidence_settings

    get_evidence_settings.cache_clear()
    yield
    get_settings.cache_clear()
    get_evidence_settings.cache_clear()


@pytest.fixture
def settings():
    return Settings(
        _env_file=None,
        app_env="test",
        database_url="",
        supabase_url="https://synthetic-project.supabase.co",
        supabase_publishable_key="synthetic-publishable-key",
        supabase_secret_key="synthetic-server-key",
        cors_origins="http://localhost:5173",
    )


@pytest.fixture
def app(settings):
    application = create_app()
    application.dependency_overrides[get_settings] = lambda: settings
    return application


@pytest.fixture
async def client(app):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as value:
        yield value


@pytest.fixture
def mock_provider(app):
    def install(handler):
        async def dependency():
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as provider:
                yield provider

        app.dependency_overrides[get_provider_client] = dependency

    return install


@pytest.fixture
def membership(monkeypatch, app):
    def install(role="finance_admin", present=True):
        async def session():
            yield object()

        app.dependency_overrides[get_session] = session

        async def lookup(_, user_id):
            assert user_id == USER_ID
            if not present:
                return None
            return (
                SimpleNamespace(role=role),
                SimpleNamespace(id=TENANT_ID, name="Synthetic test business"),
            )

        monkeypatch.setattr("app.core.auth.lookup_membership", lookup)

    return install


def valid_auth(request):
    assert request.url.path == "/auth/v1/user"
    assert request.headers["apikey"] == "synthetic-publishable-key"
    assert request.headers["authorization"] == "Bearer synthetic-session"
    return httpx.Response(
        200,
        json={
            "id": str(USER_ID),
            "email": "finance@example.invalid",
            "user_metadata": {"role": "finance_admin", "tenant_id": "attacker"},
        },
    )
