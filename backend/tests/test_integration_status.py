from app.evidence.config import EvidenceSettings, get_evidence_settings
from app.integrations.settings import SponsorSettings, get_sponsor_settings
from test_api import AUTH
from conftest import valid_auth


async def test_configured_is_not_live_verified(app, client, mock_provider, membership):
    membership()
    mock_provider(valid_auth)
    app.dependency_overrides[get_evidence_settings] = lambda: EvidenceSettings(
        _env_file=None,
        openai_api_key="synthetic",
        openai_model="synthetic-model",
        breeth_api_key="",
    )
    app.dependency_overrides[get_sponsor_settings] = lambda: SponsorSettings(
        _env_file=None, dodo_api_key="", elevenlabs_api_key="", n8n_webhook_token=""
    )
    response = await client.get("/api/integrations", headers=AUTH)
    assert response.status_code == 200
    rows = response.json()["integrations"]
    assert {item["id"] for item in rows} == {"openai", "n8n", "breeth", "elevenlabs", "dodo"}
    assert rows[0]["configured"] is True
    assert all(item["live_verified"] is False for item in rows)
    assert "synthetic-model" not in response.text and "api_key" not in response.text


async def test_supplier_cannot_read_finance_integration_configuration(
    client, mock_provider, membership
):
    membership(role="supplier")
    mock_provider(valid_auth)
    response = await client.get("/api/integrations", headers=AUTH)
    assert response.status_code == 403
