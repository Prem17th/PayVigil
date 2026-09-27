import asyncio
import hmac
from contextlib import asynccontextmanager
from typing import Annotated, Literal
from uuid import UUID

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import create_async_engine

from .config import database_url, get_settings
from .ledger import IdempotencyConflict, check_ready, create_transfer, read_transfer


class TransferRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    payment_id: UUID
    revision_id: UUID
    tenant_id: UUID
    invoice_reference: str = Field(min_length=1, max_length=120, pattern=r"^[^\x00-\x1f\x7f]+$")
    amount_minor: int = Field(gt=0, le=1_000_000_000_000, strict=True)
    currency: Literal["INR"]
    beneficiary_name: str = Field(min_length=1, max_length=160, pattern=r"^[^\x00-\x1f\x7f]+$")
    sandbox_account_id: str = Field(pattern=r"^SIM-[A-Z0-9-]{3,64}$")
    digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    simulation: Literal["success", "decline", "lost_response"]


async def authorize(authorization: Annotated[str | None, Header()] = None) -> None:
    expected = get_settings().api_key.get_secret_value()
    if not expected:
        raise HTTPException(503, "Sandbox authorization is not configured.")
    supplied = authorization or ""
    if not supplied.startswith("Bearer ") or not hmac.compare_digest(
        supplied[7:].encode(), expected.encode()
    ):
        raise HTTPException(
            401, "Sandbox authorization is required.", headers={"WWW-Authenticate": "Bearer"}
        )


def get_engine(request: Request):
    if getattr(request.app.state, "engine", None) is None:
        request.app.state.engine = create_async_engine(
            database_url(get_settings()),
            pool_pre_ping=True,
            pool_size=5,
            max_overflow=5,
            hide_parameters=True,
            echo=False,
            connect_args={"prepare_threshold": None},
        )
    return request.app.state.engine


@asynccontextmanager
async def lifespan(application: FastAPI):
    yield
    engine = getattr(application.state, "engine", None)
    if engine is not None:
        await engine.dispose()


app = FastAPI(
    title="PayVigil synthetic payment sandbox",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)


@app.exception_handler(RequestValidationError)
async def invalid_request(_: Request, __: RequestValidationError):
    return JSONResponse(status_code=422, content={"error": "Invalid synthetic transfer request."})


@app.exception_handler(Exception)
async def unavailable(_: Request, __: Exception):
    return JSONResponse(status_code=503, content={"error": "Sandbox service is unavailable."})


@app.middleware("http")
async def no_store(request: Request, call_next):
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@app.get("/health")
async def health():
    return {"status": "ok", "service": "synthetic-payment-sandbox", "real_funds": False}


@app.get("/ready")
async def ready(request: Request):
    if not get_settings().api_key.get_secret_value():
        raise HTTPException(503, "Sandbox authorization is not configured.")
    await check_ready(get_engine(request))
    return {"status": "ready", "real_funds": False}


@app.post("/v1/transfers", dependencies=[Depends(authorize)])
async def transfer(
    request: Request,
    body: TransferRequest,
    idempotency_key: Annotated[UUID, Header(alias="Idempotency-Key")],
):
    try:
        answer = await create_transfer(
            get_engine(request),
            idempotency_key,
            body.model_dump(mode="json"),
            get_settings().visibility_delay_seconds,
        )
    except IdempotencyConflict:
        raise HTTPException(409, "The idempotency key is bound to a different transfer.") from None
    if body.simulation == "lost_response":
        await asyncio.sleep(get_settings().lost_response_delay_seconds)
    return answer


@app.get("/v1/transfers/by-idempotency/{key}", dependencies=[Depends(authorize)])
async def readback(request: Request, key: UUID):
    answer = await read_transfer(get_engine(request), key)
    if answer is None:
        raise HTTPException(404, "Transfer result is not yet available.")
    return answer
