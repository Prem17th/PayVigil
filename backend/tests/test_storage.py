import httpx
import pytest

from conftest import valid_auth
from test_api import AUTH


class StorageProvider:
    """Provider double confined to tests; never imported by the runtime."""

    def __init__(
        self,
        *,
        public=False,
        leak=False,
        delete_fails=False,
        public_error=404,
        deletion_read_status=404,
    ):
        self.public = public
        self.leak = leak
        self.delete_fails = delete_fails
        self.public_error = public_error
        self.deletion_read_status = deletion_read_status
        self.objects = {}
        self.uploaded = False

    def __call__(self, request):
        path = request.url.path
        if path == "/auth/v1/user":
            return valid_auth(request)
        if path.startswith("/storage/v1/bucket/"):
            assert request.headers["apikey"] == "synthetic-server-key"
            assert "authorization" not in request.headers
            return httpx.Response(200, json={"public": self.public})
        if request.method == "POST":
            assert request.headers["apikey"] == "synthetic-server-key"
            self.objects[path] = request.content
            self.uploaded = True
            return httpx.Response(200, json={"Key": path})
        if request.method == "DELETE":
            if self.delete_fails:
                return httpx.Response(500, text="private provider exception")
            self.objects.clear()
            return httpx.Response(200, json=[])
        if "/object/authenticated/" in path:
            key = path.replace("/object/authenticated/", "/object/")
            return (
                httpx.Response(200, content=self.objects[key])
                if key in self.objects
                else httpx.Response(self.deletion_read_status)
            )
        if "/object/public/" in path:
            assert "apikey" not in request.headers
            if self.leak:
                return httpx.Response(200, content=next(iter(self.objects.values())))
            return httpx.Response(self.public_error, text="private provider diagnostic")
        assert request.headers["apikey"] == "synthetic-publishable-key"
        return httpx.Response(400, json={"statusCode": "403"})


async def test_private_storage_requires_actual_upload_read_and_cleanup(
    client, mock_provider, membership
):
    provider = StorageProvider()
    mock_provider(provider)
    membership()
    response = await client.post(
        "/api/storage/check", headers=AUTH, json={"object_path": "attacker"}
    )
    assert response.status_code == 200
    assert response.json()["status"] == "verified"
    assert response.json()["checks"] == {
        "bucket_private": True,
        "upload": True,
        "authenticated_read": True,
        "anonymous_read_denied": True,
        "deleted": True,
    }
    assert provider.uploaded and provider.objects == {}


async def test_public_bucket_never_receives_probe(client, mock_provider, membership):
    provider = StorageProvider(public=True)
    mock_provider(provider)
    membership()
    response = await client.post("/api/storage/check", headers=AUTH)
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "private_bucket_required"
    assert provider.uploaded is False


@pytest.mark.parametrize("options", [{"leak": True}, {"public_error": 500}, {"public_error": 400}])
async def test_anonymous_success_or_inconclusive_response_is_failure(
    client, mock_provider, membership, options
):
    provider = StorageProvider(**options)
    mock_provider(provider)
    membership()
    response = await client.post("/api/storage/check", headers=AUTH)
    assert response.status_code == 503
    assert provider.objects == {}
    assert "private provider" not in response.text


async def test_cleanup_failure_is_never_reported_as_verified(client, mock_provider, membership):
    provider = StorageProvider(delete_fails=True)
    mock_provider(provider)
    membership()
    response = await client.post("/api/storage/check", headers=AUTH)
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "storage_cleanup_failed"


async def test_configured_storage_is_not_verification(client):
    response = await client.get("/api/setup")
    assert response.json()["storage_configured"] is True
    assert "verified" not in response.text


@pytest.mark.parametrize("status", [401, 403, 500])
async def test_cleanup_permission_failure_is_not_proof_of_deletion(
    client, mock_provider, membership, status
):
    provider = StorageProvider(deletion_read_status=status)
    mock_provider(provider)
    membership()
    response = await client.post("/api/storage/check", headers=AUTH)
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "storage_cleanup_failed"
