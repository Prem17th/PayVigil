import httpx
import pytest

from app.core.config import Settings, get_settings
from conftest import TENANT_ID, valid_auth


AUTH = {"Authorization": "Bearer synthetic-session"}


async def test_public_liveness_and_non_secret_setup(client, app):
    app.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None,
        database_url="",
        supabase_url="",
        supabase_publishable_key="",
        supabase_secret_key="",
    )
    health = await client.get("/api/health")
    assert health.json() == {
        "status": "ok",
        "service": "beforetransfer-api",
        "version": "0.9.0",
        "phase": 9,
    }
    assert health.headers["cache-control"] == "no-store"
    setup = await client.get("/api/setup")
    assert setup.json() == {
        "auth_configured": False,
        "database_configured": False,
        "storage_configured": False,
        "phase": 9,
        "capabilities": {"payments": True, "investigations": True},
    }
    assert (await client.get("/api/me")).status_code == 503
    assert (await client.get("/api/ready")).status_code == 503


async def test_missing_bearer_is_unauthorized(client):
    response = await client.get("/api/me")
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


async def test_invalid_jwt_never_becomes_identity(client, mock_provider):
    mock_provider(lambda _: httpx.Response(401, json={"message": "private-provider-diagnostic"}))
    response = await client.get("/api/me", headers=AUTH)
    assert response.status_code == 401
    assert "private-provider-diagnostic" not in response.text


async def test_auth_timeout_is_not_authenticated(client, mock_provider):
    def unavailable(request):
        raise httpx.ReadTimeout("private credential must not leak", request=request)

    mock_provider(unavailable)
    response = await client.get("/api/me", headers=AUTH)
    assert response.status_code == 503
    assert "credential" not in response.text


async def test_missing_database_fails_closed_after_valid_auth(client, mock_provider):
    mock_provider(valid_auth)
    assert (await client.get("/api/me", headers=AUTH)).status_code == 503


async def test_membership_required(client, mock_provider, membership):
    mock_provider(valid_auth)
    membership(present=False)
    response = await client.get("/api/me", headers=AUTH)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "membership_required"


async def test_metadata_cannot_upgrade_supplier(client, mock_provider, membership):
    mock_provider(valid_auth)
    membership("supplier")
    me = await client.get("/api/me", headers=AUTH)
    assert me.json()["role"] == "supplier"
    assert me.json()["tenant"]["id"] == str(TENANT_ID)
    assert (await client.get("/api/workspace", headers=AUTH)).status_code == 403
    assert (await client.post("/api/storage/check", headers=AUTH)).status_code == 403
    portal = await client.get("/api/supplier/portal", headers=AUTH)
    assert portal.status_code == 200
    assert portal.json()["requests"] == []


@pytest.mark.parametrize("role", ["finance_admin", "finance_reviewer"])
async def test_tenant_and_role_are_not_query_parameters(client, mock_provider, membership, role):
    mock_provider(valid_auth)
    membership(role)
    response = await client.get("/api/workspace?tenant_id=attacker&role=supplier", headers=AUTH)
    assert response.status_code == 200
    assert response.json()["tenant"]["id"] == str(TENANT_ID)
    assert response.json()["role"] == role
    assert response.json()["cases"] == []
    assert response.json()["capabilities"] == {"payments": True, "investigations": True}
    assert (await client.get("/api/supplier/portal", headers=AUTH)).status_code == 403


async def test_unknown_membership_role_cannot_authorize(client, mock_provider, membership):
    mock_provider(valid_auth)
    membership("superuser")
    assert (await client.get("/api/me", headers=AUTH)).status_code == 403


async def test_docs_are_not_public_runtime_endpoints(client):
    assert (await client.get("/docs")).status_code == 404
    assert (await client.get("/openapi.json")).status_code == 404
