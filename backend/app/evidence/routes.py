from typing import Annotated
from urllib.parse import quote
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, Response

from app.evidence import domain
from app.core.config import Settings, get_settings
from app.evidence.config import EvidenceSettings, get_evidence_settings
from app.evidence.providers import retrieve_memory
from app.evidence.schemas import EvidenceUpload, InvestigationCreate, InvestigationReviewBody
from app.payments.domain import payment_rows, transaction
from app.payments.routes import Finance, Session
from app.core.providers import get_provider_client


router = APIRouter(prefix="/api")
Provider = Annotated[httpx.AsyncClient, Depends(get_provider_client)]
StorageConfig = Annotated[Settings, Depends(get_settings)]
EvidenceConfig = Annotated[EvidenceSettings, Depends(get_evidence_settings)]


@router.get("/payments/{payment_id}/evidence")
async def evidence(payment_id: UUID, session: Session, principal: Finance):
    return await domain.get_evidence(session, principal, payment_id)


@router.post("/payments/{payment_id}/evidence")
async def upload(
    payment_id: UUID,
    body: EvidenceUpload,
    session: Session,
    principal: Finance,
    client: Provider,
    settings: StorageConfig,
):
    return await domain.upload_evidence(session, principal, payment_id, body, client, settings)


@router.get("/evidence/{document_id}/content")
async def original(
    document_id: UUID,
    session: Session,
    principal: Finance,
    client: Provider,
    settings: StorageConfig,
):
    raw, filename, media_type = await domain.read_original(
        session, principal, document_id, client, settings
    )
    return Response(
        raw,
        media_type=media_type,
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename, safe='')}",
            "Cache-Control": "no-store",
        },
    )


@router.get("/payments/{payment_id}/investigations")
async def investigations(payment_id: UUID, session: Session, principal: Finance):
    return await domain.list_investigations(session, principal, payment_id)


@router.post("/payments/{payment_id}/investigations")
async def investigate(
    payment_id: UUID,
    body: InvestigationCreate,
    session: Session,
    principal: Finance,
    client: Provider,
    settings: EvidenceConfig,
):
    return await domain.investigate(
        session, principal, payment_id, body.revision_id, client, settings
    )


@router.post("/investigations/{investigation_id}/reviews")
async def review(
    investigation_id: UUID, body: InvestigationReviewBody, session: Session, principal: Finance
):
    return await domain.review_investigation(session, principal, investigation_id, body.note)


@router.post("/investigations/{investigation_id}/memory")
async def remember(
    investigation_id: UUID,
    session: Session,
    principal: Finance,
    client: Provider,
    settings: EvidenceConfig,
):
    return await domain.remember_investigation(
        session, principal, investigation_id, client, settings
    )


@router.get("/payments/{payment_id}/memory")
async def memory(
    payment_id: UUID,
    session: Session,
    principal: Finance,
    client: Provider,
    settings: EvidenceConfig,
):
    async with transaction(session, principal):
        await payment_rows(session, payment_id, principal.tenant.id)
    return {"items": await retrieve_memory(client, settings, principal.tenant.id)}
