"""Local identity provider double. Real Supabase verification remains pending."""

import base64
import hashlib
import hmac
import json
import os
import time
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response


def _encode(value: dict) -> str:
    return (
        base64.urlsafe_b64encode(json.dumps(value, separators=(",", ":")).encode())
        .decode()
        .rstrip("=")
    )


def create_app() -> FastAPI:
    if os.environ.get("APP_ENV") != "test":
        raise RuntimeError("The local identity simulator requires explicit APP_ENV=test.")
    path = Path(os.environ["LOCAL_DEMO_IDENTITY_FILE"]).resolve()
    expected = Path(__file__).resolve().parents[1] / ".local" / "demo"
    if not path.is_relative_to(expected):
        raise RuntimeError("Identity fixtures must be in this workspace's ignored demo directory.")
    state = json.loads(path.read_text())
    secret = state["signing_secret"].encode()
    public_key = state["publishable_key"]
    storage_key = state["storage_key"]
    actors = state["actors"]
    issuer = state["identity_origin"]
    frontend_origin = state["frontend_origin"]
    for origin in (issuer, frontend_origin):
        parsed = urlsplit(origin)
        if (
            parsed.scheme != "http"
            or parsed.hostname not in {"127.0.0.1", "localhost"}
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path
        ):
            raise RuntimeError("Local simulator origins must be plain loopback origins.")
    revoked: set[str] = set()
    storage_root = expected / "objects"
    storage_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    app = FastAPI(title="Local synthetic identity simulator", docs_url=None, openapi_url=None)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[frontend_origin],
        allow_methods=["GET", "POST"],
        allow_headers=[
            "Authorization",
            "apikey",
            "Content-Type",
            "X-Client-Info",
            "X-Supabase-Api-Version",
        ],
    )

    @app.middleware("http")
    async def loopback_only(request: Request, call_next):
        if (
            not request.client
            or request.client.host not in {"127.0.0.1", "::1"}
            or request.url.hostname not in {"127.0.0.1", "localhost"}
        ):
            return JSONResponse({"error": "Loopback test access only"}, status_code=403)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        return response

    def user(actor: dict) -> dict:
        return {
            "id": actor["user_id"],
            "aud": "authenticated",
            "role": "authenticated",
            "email": actor["email"],
            "email_confirmed_at": "2026-01-01T00:00:00Z",
            "created_at": "2026-01-01T00:00:00Z",
            "app_metadata": {"provider": "local-synthetic"},
            "user_metadata": {},
            "identities": [],
            "is_anonymous": False,
        }

    def session(actor: dict) -> dict:
        now = int(time.time())
        head = _encode({"alg": "HS256", "typ": "JWT"})
        payload = _encode(
            {
                "iss": issuer + "/auth/v1",
                "sub": actor["user_id"],
                "aud": "authenticated",
                "role": "authenticated",
                "email": actor["email"],
                "iat": now,
                "exp": now + 3600,
                "jti": uuid4().hex,
            }
        )
        unsigned = f"{head}.{payload}"
        signature = (
            base64.urlsafe_b64encode(hmac.new(secret, unsigned.encode(), hashlib.sha256).digest())
            .decode()
            .rstrip("=")
        )
        return {
            "access_token": f"{unsigned}.{signature}",
            "token_type": "bearer",
            "expires_in": 3600,
            "expires_at": now + 3600,
            "refresh_token": actor["refresh_token"],
            "user": user(actor),
        }

    def verify(request: Request) -> tuple[dict, dict]:
        if not hmac.compare_digest(request.headers.get("apikey", ""), public_key):
            raise HTTPException(401, "Invalid synthetic project key")
        token = request.headers.get("authorization", "")
        try:
            if not token.startswith("Bearer "):
                raise ValueError
            header, payload, signature = token[7:].split(".")
            expected_signature = (
                base64.urlsafe_b64encode(
                    hmac.new(secret, f"{header}.{payload}".encode(), hashlib.sha256).digest()
                )
                .decode()
                .rstrip("=")
            )
            if not hmac.compare_digest(signature, expected_signature):
                raise ValueError
            claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
            if (
                claims["exp"] <= time.time()
                or claims["iss"] != issuer + "/auth/v1"
                or claims["jti"] in revoked
            ):
                raise ValueError
            actor = next(item for item in actors.values() if item["user_id"] == claims["sub"])
            return actor, claims
        except (ValueError, KeyError, TypeError, StopIteration):
            raise HTTPException(401, "Invalid synthetic session") from None

    @app.get("/auth/v1/health")
    async def health():
        return {"name": "local-identity-simulator", "simulated": True}

    @app.get("/local-demo/session")
    async def issue_session(actor: str):
        # Deliberately public only on loopback: these identities control fake data.
        if actor not in actors:
            raise HTTPException(404, "Unknown synthetic actor")
        return session(actors[actor])

    @app.get("/auth/v1/user")
    async def get_user(request: Request):
        actor, _ = verify(request)
        return user(actor)

    @app.post("/auth/v1/token")
    async def refresh(request: Request, grant_type: str = ""):
        if grant_type != "refresh_token" or not hmac.compare_digest(
            request.headers.get("apikey", ""), public_key
        ):
            raise HTTPException(400, "Use the explicitly labelled local identity switch")
        body = await request.json()
        candidate = body.get("refresh_token")
        if not isinstance(candidate, str):
            raise HTTPException(401, "Invalid synthetic refresh token")
        actor = next(
            (
                item
                for item in actors.values()
                if hmac.compare_digest(item["refresh_token"], candidate)
            ),
            None,
        )
        if actor is None:
            raise HTTPException(401, "Invalid synthetic refresh token")
        return session(actor)

    @app.post("/auth/v1/logout")
    async def logout(request: Request):
        _, claims = verify(request)
        revoked.add(claims["jti"])
        return Response(status_code=204)

    def storage_access(request: Request) -> None:
        if not hmac.compare_digest(request.headers.get("apikey", ""), storage_key):
            raise HTTPException(403, "Private synthetic storage")

    def object_file(bucket: str, key: str) -> Path:
        if bucket != "beforetransfer-evidence":
            raise HTTPException(404, "Unknown synthetic bucket")
        path = (storage_root / key).resolve()
        if not key or path == storage_root or not path.is_relative_to(storage_root):
            raise HTTPException(400, "Invalid object path")
        return path

    @app.get("/storage/v1/bucket/{bucket}")
    async def bucket_metadata(bucket: str, request: Request):
        storage_access(request)
        if bucket != "beforetransfer-evidence":
            raise HTTPException(404, "Unknown synthetic bucket")
        return {"id": bucket, "name": bucket, "public": False, "simulated": True}

    @app.post("/storage/v1/object/{bucket}/{key:path}")
    async def upload_object(bucket: str, key: str, request: Request):
        storage_access(request)
        path = object_file(bucket, key)
        data = await request.body()
        if len(data) > 10 * 1024 * 1024:
            raise HTTPException(413, "Synthetic fixture too large")
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with path.open("xb") as target:
                target.write(data)
            path.chmod(0o600)
        except FileExistsError:
            raise HTTPException(409, "Object already exists") from None
        return {"Key": f"{bucket}/{key}"}

    @app.get("/storage/v1/object/public/{bucket}/{key:path}")
    async def public_object(bucket: str, key: str):
        raise HTTPException(404, "Private synthetic object")

    @app.get("/storage/v1/object/{bucket}/{key:path}")
    @app.get("/storage/v1/object/authenticated/{bucket}/{key:path}")
    async def read_object(bucket: str, key: str, request: Request):
        storage_access(request)
        path = object_file(bucket, key)
        if not path.is_file():
            raise HTTPException(404, "Object not found")
        return Response(path.read_bytes(), media_type="application/octet-stream")

    @app.delete("/storage/v1/object/{bucket}")
    async def delete_objects(bucket: str, request: Request):
        storage_access(request)
        body = await request.json()
        prefixes = body.get("prefixes")
        if (
            not isinstance(prefixes, list)
            or len(prefixes) > 20
            or any(not isinstance(value, str) for value in prefixes)
        ):
            raise HTTPException(400, "Invalid object list")
        deleted = []
        for key in prefixes:
            path = object_file(bucket, key)
            if path.is_file():
                path.unlink()
                deleted.append({"name": key})
        return deleted

    return app


app = create_app()
