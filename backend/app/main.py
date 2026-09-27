from contextlib import asynccontextmanager

import httpx
from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_principal, require_finance, require_supplier
from app.core.config import Settings, get_settings
from app.core.database import get_session, verify_database
from app.core.errors import AppError, app_error_handler
from app.core.providers import api_key_headers, get_provider_client
from app.payments.routes import router as payment_router
from app.integrations.status import router as integration_router
from app.evidence.routes import router as evidence_router
from app.integrations.routes import router as sponsor_router
from app.core.request_limits import RequestLimitMiddleware
from app.core.schemas import (
    Principal,
    SetupView,
    StorageCheckView,
    SupplierPortalView,
    WorkspaceView,
)
from app.core.storage import check_private_storage, ensure_private_bucket


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    engine = getattr(app.state, "database_engine", None)
    if engine is not None:
        await engine.dispose()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="PayVigil",
        version="0.9.0",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.add_exception_handler(AppError, app_error_handler)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type", "Idempotency-Key"],
    )
    app.include_router(payment_router)
    app.include_router(integration_router)
    app.include_router(evidence_router)
    app.include_router(sponsor_router)
    app.add_middleware(RequestLimitMiddleware)

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, __: RequestValidationError):
        return JSONResponse(
            status_code=422,
            content={"error": {"code": "invalid_request", "message": "The request is invalid."}},
        )

    @app.exception_handler(Exception)
    async def unexpected_error(_: Request, __: Exception):
        return JSONResponse(
            status_code=503,
            content={
                "error": {
                    "code": "service_unavailable",
                    "message": "The service is temporarily unavailable.",
                }
            },
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/api/health")
    async def health():
        return {"status": "ok", "service": "beforetransfer-api", "version": "0.9.0", "phase": 9}

    @app.get("/api/setup", response_model=SetupView)
    async def setup(settings: Settings = Depends(get_settings)):
        return SetupView(
            auth_configured=settings.auth_configured,
            database_configured=settings.database_configured,
            storage_configured=settings.storage_configured,
        )

    @app.get("/api/ready")
    async def ready(
        settings: Settings = Depends(get_settings),
        session: AsyncSession = Depends(get_session),
        client: httpx.AsyncClient = Depends(get_provider_client),
    ):
        if not settings.auth_configured or not settings.storage_configured:
            raise AppError(503, "setup_incomplete", "Required provider configuration is missing.")
        await verify_database(session)
        try:
            response = await client.get(
                f"{settings.provider_url}/auth/v1/health",
                headers=api_key_headers(settings.supabase_publishable_key.get_secret_value()),
            )
        except httpx.HTTPError:
            raise AppError(
                503, "auth_unavailable", "Authentication readiness could not be verified."
            ) from None
        if response.status_code != 200:
            raise AppError(
                503, "auth_unavailable", "Authentication readiness could not be verified."
            )
        await ensure_private_bucket(client, settings)
        return {"status": "ready", "phase": 9}

    @app.get("/api/me", response_model=Principal)
    async def me(principal: Principal = Depends(get_principal)):
        return principal

    @app.get("/api/workspace", response_model=WorkspaceView)
    async def workspace(principal: Principal = Depends(require_finance)):
        return WorkspaceView(tenant=principal.tenant, role=principal.role)

    @app.get("/api/supplier/portal", response_model=SupplierPortalView)
    async def supplier_portal(principal: Principal = Depends(require_supplier)):
        return SupplierPortalView(tenant=principal.tenant)

    @app.post("/api/storage/check", response_model=StorageCheckView)
    async def storage_check(
        principal: Principal = Depends(require_finance),
        settings: Settings = Depends(get_settings),
        client: httpx.AsyncClient = Depends(get_provider_client),
    ):
        return await check_private_storage(client, settings, principal.tenant.id)

    return app


app = create_app()
