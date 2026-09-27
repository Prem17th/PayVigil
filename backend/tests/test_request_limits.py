import httpx
import pytest
from fastapi import FastAPI, Request

from app.core.request_limits import RequestLimitMiddleware


@pytest.mark.parametrize("claimed_length", [None, "1", "999999"])
async def test_actual_bytes_limited_before_handler(claimed_length):
    app = FastAPI()
    app.add_middleware(RequestLimitMiddleware, max_bytes=32)
    invoked = False

    @app.post("/upload")
    async def upload(request: Request):
        nonlocal invoked
        invoked = True
        return {"length": len(await request.body())}

    async def chunks():
        yield b"a" * 16
        yield b"b" * 17

    headers = {"Content-Length": claimed_length} if claimed_length else {}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/upload", content=chunks(), headers=headers)
    assert response.status_code == 413 and not invoked
    assert response.headers["cache-control"] == "no-store"


async def test_body_within_limit_preserved_exactly():
    app = FastAPI()
    app.add_middleware(RequestLimitMiddleware, max_bytes=32)

    @app.post("/upload")
    async def upload(request: Request):
        return {"body": (await request.body()).decode()}

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/upload", content="{" + "x" * 30 + "}")
    assert response.status_code == 200 and response.json()["body"] == "{" + "x" * 30 + "}"
