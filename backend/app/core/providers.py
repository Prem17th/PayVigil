from collections.abc import AsyncIterator

import httpx


async def get_provider_client() -> AsyncIterator[httpx.AsyncClient]:
    # Keys must never follow a redirect to another origin; no request logging.
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(8.0, connect=3.0),
        follow_redirects=False,
        trust_env=False,
    ) as client:
        yield client


def api_key_headers(key: str) -> dict[str, str]:
    headers = {"apikey": key}
    # New sb_secret / sb_publishable values are not JWTs. Legacy keys are.
    if key.startswith("eyJ"):
        headers["Authorization"] = f"Bearer {key}"
    return headers
