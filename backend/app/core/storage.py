import asyncio
from datetime import datetime, timezone
from urllib.parse import quote
from uuid import UUID, uuid4

import httpx

from app.core.config import Settings
from app.core.errors import AppError
from app.core.providers import api_key_headers
from app.core.schemas import StorageCheckView


def _failure(
    code: str = "storage_unavailable", message: str = "Private storage verification failed."
) -> AppError:
    return AppError(503, code, message)


def _denied(response: httpx.Response) -> bool:
    if response.status_code in {401, 403, 404}:
        return True
    # Storage sometimes wraps a 404/403 in HTTP 400. A generic 400 is not proof.
    if response.status_code == 400:
        try:
            return str(response.json().get("statusCode")) in {"401", "403", "404"}
        except (ValueError, AttributeError):
            return False
    return False


def _not_found(response: httpx.Response) -> bool:
    if response.status_code == 404:
        return True
    if response.status_code == 400:
        try:
            return str(response.json().get("statusCode")) == "404"
        except (ValueError, AttributeError):
            return False
    return False


async def ensure_private_bucket(client: httpx.AsyncClient, settings: Settings) -> None:
    if not settings.storage_configured:
        raise _failure("storage_not_configured", "Private storage is not configured.")
    try:
        response = await client.get(
            f"{settings.provider_url}/storage/v1/bucket/{quote(settings.supabase_storage_bucket, safe='')}",
            headers=api_key_headers(settings.supabase_secret_key.get_secret_value()),
        )
        body = response.json() if response.status_code == 200 else None
        if not isinstance(body, dict) or body.get("public") is not False:
            raise _failure(
                "private_bucket_required",
                "The configured storage bucket must exist and be private.",
            )
    except (httpx.HTTPError, ValueError):
        raise _failure() from None


async def check_private_storage(
    client: httpx.AsyncClient, settings: Settings, tenant_id: UUID
) -> StorageCheckView:
    await ensure_private_bucket(client, settings)
    bucket = quote(settings.supabase_storage_bucket, safe="")
    key = f"phase2-checks/{tenant_id}/{uuid4().hex}.txt"
    object_path = f"{bucket}/{key}"
    base = f"{settings.provider_url}/storage/v1"
    headers = api_key_headers(settings.supabase_secret_key.get_secret_value())
    payload = f"beforetransfer-phase2-probe:{uuid4().hex}".encode()
    upload_attempted = False
    failure: AppError | None = None
    try:
        async with asyncio.timeout(35):
            upload_attempted = True
            response = await client.post(
                f"{base}/object/{object_path}",
                content=payload,
                headers={**headers, "Content-Type": "text/plain", "x-upsert": "false"},
            )
            if response.status_code not in {200, 201}:
                raise _failure("storage_upload_failed")
            response = await client.get(
                f"{base}/object/authenticated/{object_path}", headers=headers
            )
            if response.status_code != 200 or response.content != payload:
                raise _failure("storage_read_failed")
            # Check both the public route and anonymous policy access to the normal route.
            public = await client.get(f"{base}/object/public/{object_path}")
            anonymous = await client.get(
                f"{base}/object/{object_path}",
                headers=api_key_headers(settings.supabase_publishable_key.get_secret_value()),
            )
            if not _denied(public) or not _denied(anonymous):
                raise _failure(
                    "storage_anonymous_access", "Anonymous storage access was not safely denied."
                )
    except AppError as error:
        failure = error
    except (httpx.HTTPError, TimeoutError):
        failure = _failure()
    finally:
        # Also attempt cleanup after a timeout: the upload may have committed.
        if upload_attempted:
            try:
                async with asyncio.timeout(15):
                    deleted = await client.request(
                        "DELETE",
                        f"{base}/object/{bucket}",
                        json={"prefixes": [key]},
                        headers=headers,
                    )
                    after = await client.get(
                        f"{base}/object/authenticated/{object_path}", headers=headers
                    )
                    if deleted.status_code not in {200, 204} or not _not_found(after):
                        raise _failure()
            except (AppError, httpx.HTTPError, TimeoutError):
                failure = _failure(
                    "storage_cleanup_failed", "Storage probe cleanup could not be verified."
                )
    if failure:
        raise failure
    return StorageCheckView(checked_at=datetime.now(timezone.utc))
