import asyncio
import hashlib
import json
from datetime import timedelta
from urllib.parse import quote
from uuid import UUID, uuid4

import httpx
from sqlalchemy import func, select

from app.core.config import Settings
from app.core.errors import AppError
from app.evidence.config import EvidenceSettings
from app.evidence.models import (
    EvidenceDocument,
    Investigation,
    InvestigationReview,
    MemoryOperation,
)
from app.evidence.providers import (
    extract_document,
    run_investigation_agent,
    safe_review_summary,
    write_memory,
)
from app.evidence.schemas import EvidenceUpload
from app.payments.domain import (
    LOCKED_PAYMENT_STATES,
    audit,
    conflict,
    now,
    payment_rows,
    sandbox_body,
    transaction,
)
from app.payments.models import BeneficiaryVersion, Payment
from app.core.providers import api_key_headers
from app.core.storage import _denied, ensure_private_bucket


EMPTY_EVIDENCE_DIGEST = hashlib.sha256(b"[]").hexdigest()


async def evidence_state(session, payment_id: UUID):
    docs = (
        await session.scalars(
            select(EvidenceDocument)
            .where(EvidenceDocument.payment_id == payment_id, EvidenceDocument.status != "failed")
            .order_by(EvidenceDocument.id)
        )
    ).all()
    payload = [{"id": str(d.id), "sha256": d.sha256, "status": d.status} for d in docs]
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return digest, docs


async def evidence_holds(session, payment: Payment, revision_id: UUID) -> list[str]:
    digest, docs = await evidence_state(session, payment.id)
    if not docs:
        return []
    if any(d.status != "ready" for d in docs):
        return [
            "Private evidence upload is incomplete or uncertain. Resolve its storage state before approval."
        ]
    reviewed = await session.scalar(
        select(Investigation.id)
        .join(InvestigationReview, InvestigationReview.investigation_id == Investigation.id)
        .where(
            Investigation.payment_id == payment.id,
            Investigation.revision_id == revision_id,
            Investigation.evidence_digest == digest,
            Investigation.status == "completed",
        )
    )
    return (
        []
        if reviewed
        else [
            "A completed investigation and human acknowledgement of the current evidence snapshot are required."
        ]
    )


def document_view(document):
    return {
        "id": document.id,
        "payment_id": document.payment_id,
        "revision_id": document.revision_id,
        "filename": document.filename,
        "media_type": document.media_type,
        "sha256": document.sha256,
        "created_at": document.created_at,
        "extracted_text": document.extracted_text,
        "extraction_status": "extracted" if document.status == "ready" else document.status,
    }


async def get_evidence(session, principal, payment_id):
    async with transaction(session, principal):
        await payment_rows(session, payment_id, principal.tenant.id)
        docs = (
            await session.scalars(
                select(EvidenceDocument)
                .where(EvidenceDocument.payment_id == payment_id)
                .order_by(EvidenceDocument.created_at)
            )
        ).all()
        return {"documents": [document_view(d) for d in docs]}


async def bounded_storage_read(client, settings, object_path):
    url = f"{settings.provider_url}/storage/v1/object/authenticated/{quote(settings.supabase_storage_bucket, safe='')}/{object_path}"
    async with client.stream(
        "GET",
        url,
        headers={
            **api_key_headers(settings.supabase_secret_key.get_secret_value()),
            "Accept-Encoding": "identity",
        },
    ) as response:
        if response.status_code != 200:
            raise AppError(
                503, "evidence_storage_unavailable", "The private original could not be read back."
            )
        if response.headers.get("content-encoding", "identity").lower() != "identity":
            raise AppError(
                503, "evidence_storage_invalid", "Compressed original responses are not accepted."
            )
        raw = bytearray()
        async for chunk in response.aiter_raw():
            raw.extend(chunk)
            if len(raw) > 2 * 1024 * 1024:
                raise AppError(
                    503,
                    "evidence_storage_invalid",
                    "The stored original exceeds its verified size limit.",
                )
    return bytes(raw)


async def upload_evidence(
    session,
    principal,
    payment_id,
    body: EvidenceUpload,
    client: httpx.AsyncClient,
    settings: Settings,
):
    if not settings.storage_configured:
        raise AppError(503, "storage_not_configured", "Private evidence storage is not configured.")
    raw, pages = await extract_document(body.content_base64, body.media_type)
    digest = hashlib.sha256(raw).hexdigest()
    recover = False
    async with transaction(session, principal):
        _, payment, revision = await payment_rows(
            session, payment_id, principal.tenant.id, lock=True
        )
        if payment.state in LOCKED_PAYMENT_STATES:
            raise conflict("payment_locked", "Evidence cannot change after execution is queued.")
        if revision.id != body.revision_id:
            raise conflict(
                "stale_revision", "Upload evidence against the current immutable revision."
            )
        document = await session.scalar(
            select(EvidenceDocument).where(
                EvidenceDocument.payment_id == payment.id,
                EvidenceDocument.revision_id == revision.id,
                EvidenceDocument.sha256 == digest,
            )
        )
        if document:
            if document.status == "ready":
                return document_view(document)
            if document.status == "uploading" and document.created_at < now() - timedelta(
                minutes=1
            ):
                document.status = "unknown"
            if document.status != "unknown":
                raise conflict(
                    "evidence_operation_exists",
                    "This evidence already has an incomplete or failed upload operation.",
                )
            recover = True
        else:
            count = await session.scalar(
                select(func.count())
                .select_from(EvidenceDocument)
                .where(EvidenceDocument.payment_id == payment.id)
            )
            if count >= 10:
                raise conflict(
                    "evidence_limit", "A payment may contain at most ten evidence documents."
                )
            document_id = uuid4()
            document = EvidenceDocument(
                id=document_id,
                tenant_id=principal.tenant.id,
                payment_id=payment.id,
                revision_id=revision.id,
                filename=body.filename,
                media_type=body.media_type,
                sha256=digest,
                object_path=f"evidence/{principal.tenant.id}/{payment.id}/{document_id}.bin",
                extracted_text="\n".join(p["text"] for p in pages),
                pages=pages,
                status="uploading",
                uploaded_by=principal.user_id,
            )
            session.add(document)
            await session.flush()
            audit(
                session,
                payment.tenant_id,
                "payment",
                payment.id,
                "evidence_upload_started",
                principal.user_id,
                document_id=str(document.id),
            )
        document_id, object_path = document.id, document.object_path
    # Every external call is outside database locks and transactions.
    outcome = "unknown"
    try:
        async with asyncio.timeout(35):
            await ensure_private_bucket(client, settings)
            bucket = quote(settings.supabase_storage_bucket, safe="")
            base = f"{settings.provider_url}/storage/v1"
            if not recover:
                response = await client.post(
                    f"{base}/object/{bucket}/{object_path}",
                    content=raw,
                    headers={
                        **api_key_headers(settings.supabase_secret_key.get_secret_value()),
                        "Content-Type": body.media_type,
                        "x-upsert": "false",
                    },
                )
                if response.status_code not in {200, 201}:
                    raise AppError(
                        503,
                        "evidence_upload_uncertain",
                        "The original upload did not produce a verifiable receipt.",
                    )
            stored = await bounded_storage_read(client, settings, object_path)
            if hashlib.sha256(stored).hexdigest() != digest:
                raise AppError(
                    503,
                    "evidence_storage_invalid",
                    "The stored original failed its content hash check.",
                )
            anonymous = await client.get(
                f"{base}/object/{bucket}/{object_path}",
                headers=api_key_headers(settings.supabase_publishable_key.get_secret_value()),
            )
            public = await client.get(f"{base}/object/public/{bucket}/{object_path}")
            if not _denied(anonymous) or not _denied(public):
                raise AppError(
                    503,
                    "evidence_storage_not_private",
                    "Anonymous access to the original was not safely denied.",
                )
            outcome = "ready"
    except (AppError, httpx.HTTPError, TimeoutError):
        pass
    async with transaction(session, principal):
        _, payment, _ = await payment_rows(session, payment_id, principal.tenant.id, lock=True)
        document = await session.scalar(
            select(EvidenceDocument)
            .where(EvidenceDocument.id == document_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        document.status = outcome
        audit(
            session,
            payment.tenant_id,
            "payment",
            payment.id,
            "evidence_verified" if outcome == "ready" else "evidence_upload_unknown",
            principal.user_id,
            document_id=str(document.id),
        )
        await session.flush()
        result = document_view(document)
    if outcome != "ready":
        raise AppError(
            503,
            "evidence_upload_unknown",
            "The original upload could not be verified. Repeating the same upload checks readback without sending another copy.",
        )
    return result


async def read_original(session, principal, document_id, client, settings):
    if not settings.storage_configured:
        raise AppError(503, "storage_not_configured", "Private storage is not configured.")
    async with transaction(session, principal):
        document = await session.scalar(
            select(EvidenceDocument).where(
                EvidenceDocument.id == document_id,
                EvidenceDocument.tenant_id == principal.tenant.id,
            )
        )
        if not document or document.status != "ready":
            raise AppError(404, "evidence_not_found", "The verified original is not available.")
        object_path, digest, filename, media_type = (
            document.object_path,
            document.sha256,
            document.filename,
            document.media_type,
        )
    try:
        raw = await bounded_storage_read(client, settings, object_path)
    except httpx.HTTPError:
        raise AppError(
            503, "evidence_storage_unavailable", "The original is temporarily unavailable."
        ) from None
    if hashlib.sha256(raw).hexdigest() != digest:
        raise AppError(
            503, "evidence_storage_invalid", "The original failed its content hash verification."
        )
    return raw, filename, media_type


async def serialize_investigation(session, record):
    payment = await session.get(Payment, record.payment_id)
    digest, documents = await evidence_state(session, record.payment_id)
    review = await session.scalar(
        select(InvestigationReview).where(InvestigationReview.investigation_id == record.id)
    )
    current = (
        payment.current_revision_id == record.revision_id
        and digest == record.evidence_digest
        and all(d.status == "ready" for d in documents)
    )
    return {
        "id": record.id,
        "payment_id": record.payment_id,
        "revision_id": record.revision_id,
        "status": record.status,
        "summary": record.summary,
        "findings": record.findings,
        "tool_trace": record.tool_trace,
        "review": {"reviewed_at": review.created_at, "note": review.note} if review else None,
        "created_at": record.created_at,
        "provider": record.provider,
        "advisory": True,
        "evidence_digest": record.evidence_digest,
        "is_current": current,
    }


async def list_investigations(session, principal, payment_id):
    async with transaction(session, principal):
        await payment_rows(session, payment_id, principal.tenant.id)
        records = (
            await session.scalars(
                select(Investigation)
                .where(Investigation.payment_id == payment_id)
                .order_by(Investigation.created_at.desc())
            )
        ).all()
        return {"investigations": [await serialize_investigation(session, r) for r in records]}


async def investigate(
    session, principal, payment_id, revision_id, client, settings: EvidenceSettings
):
    if not settings.openai_configured:
        raise AppError(
            503,
            "openai_not_configured",
            "Investigation requires OpenAI credentials and a configured model.",
        )
    async with transaction(session, principal):
        _, payment, revision = await payment_rows(
            session, payment_id, principal.tenant.id, lock=True
        )
        if revision.id != revision_id:
            raise conflict("stale_revision", "Investigate the current payment revision.")
        if payment.state in LOCKED_PAYMENT_STATES:
            raise conflict(
                "payment_locked",
                "An executing or terminal payment cannot start another investigation.",
            )
        digest, docs = await evidence_state(session, payment.id)
        if not docs or any(d.status != "ready" for d in docs):
            raise conflict(
                "verified_evidence_required", "Upload and verify readable private evidence first."
            )
        existing = await session.scalar(
            select(Investigation).where(
                Investigation.payment_id == payment.id,
                Investigation.revision_id == revision.id,
                Investigation.evidence_digest == digest,
            )
        )
        if existing:
            # The durable operation is returned rather than creating another
            # model bill after an uncertain response or a browser retry.
            if existing.status == "running" and existing.created_at < now() - timedelta(minutes=3):
                existing.status = "unknown"
                existing.summary = (
                    "The provider outcome was not verified. No automatic retry was issued."
                )
                await session.flush()
            return await serialize_investigation(session, existing)
        running = await session.scalar(
            select(Investigation).where(
                Investigation.payment_id == payment.id, Investigation.status == "running"
            )
        )
        if running:
            if running.created_at > now() - timedelta(minutes=3):
                raise conflict(
                    "investigation_in_progress",
                    "An investigation is already running for this payment.",
                )
            running.status = "unknown"
            running.summary = "The previous investigation did not return a verified result."
            await session.flush()
        count = await session.scalar(
            select(func.count())
            .select_from(Investigation)
            .where(Investigation.payment_id == payment.id)
        )
        if count >= 5:
            raise conflict(
                "investigation_limit", "This payment has reached its five-investigation cost limit."
            )
        beneficiary = await session.get(BeneficiaryVersion, revision.beneficiary_version_id)
        snapshot = sandbox_body(payment, revision, beneficiary)
        documents = [
            {
                "id": str(d.id),
                "filename": d.filename,
                "revision_id": str(d.revision_id),
                "pages": d.pages,
            }
            for d in docs
        ]
        record = Investigation(
            id=uuid4(),
            tenant_id=principal.tenant.id,
            payment_id=payment.id,
            revision_id=revision.id,
            evidence_digest=digest,
            document_ids=[str(d.id) for d in docs],
            status="running",
            summary="",
            findings=[],
            tool_trace=[],
            provider="openai",
            created_by=principal.user_id,
        )
        session.add(record)
        await session.flush()
        investigation_id = record.id
        audit(
            session,
            payment.tenant_id,
            "payment",
            payment.id,
            "investigation_started",
            principal.user_id,
            investigation_id=str(record.id),
            evidence_digest=digest,
        )
    trace = []
    try:
        result, trace = await run_investigation_agent(
            client, settings, principal.tenant.id, snapshot, documents, trace
        )
        status = "completed"
    except (TimeoutError, httpx.HTTPError):
        status = "unknown"
        result = {
            "summary": "The provider outcome was not verified. No review or payment hold was cleared.",
            "findings": [],
        }
    except Exception:
        status = "failed"
        result = {
            "summary": "The investigation did not produce a valid, source-grounded result. No hold was cleared.",
            "findings": [],
        }
    async with transaction(session, principal):
        _, payment, _ = await payment_rows(session, payment_id, principal.tenant.id, lock=True)
        record = await session.scalar(
            select(Investigation)
            .where(Investigation.id == investigation_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if record.status == "running":
            record.status, record.summary, record.findings, record.tool_trace = (
                status,
                result["summary"],
                result["findings"],
                trace,
            )
            audit(
                session,
                payment.tenant_id,
                "payment",
                payment.id,
                "investigation_" + status,
                principal.user_id,
                investigation_id=str(record.id),
            )
            await session.flush()
        return await serialize_investigation(session, record)


async def require_current_investigation(session, principal, investigation_id):
    record = await session.scalar(
        select(Investigation).where(
            Investigation.id == investigation_id, Investigation.tenant_id == principal.tenant.id
        )
    )
    if not record:
        raise AppError(404, "investigation_not_found", "The investigation is not available.")
    _, payment, _ = await payment_rows(session, record.payment_id, principal.tenant.id, lock=True)
    data = await serialize_investigation(session, record)
    if record.status != "completed" or not data["is_current"]:
        raise conflict(
            "stale_investigation",
            "A completed investigation of the current revision and evidence is required.",
        )
    return record, payment


async def require_reviewed_investigation(session, principal, investigation_id):
    record, _ = await require_current_investigation(session, principal, investigation_id)
    review = await session.scalar(
        select(InvestigationReview.id).where(InvestigationReview.investigation_id == record.id)
    )
    if not review:
        raise conflict(
            "investigation_review_required", "Finance must review this current investigation first."
        )
    return record


async def review_investigation(session, principal, investigation_id, note):
    async with transaction(session, principal):
        record, payment = await require_current_investigation(session, principal, investigation_id)
        if payment.state in LOCKED_PAYMENT_STATES:
            raise conflict(
                "payment_locked", "Investigation review cannot change after execution is queued."
            )
        review = await session.scalar(
            select(InvestigationReview).where(InvestigationReview.investigation_id == record.id)
        )
        if not review:
            session.add(
                InvestigationReview(
                    id=uuid4(),
                    tenant_id=principal.tenant.id,
                    investigation_id=record.id,
                    reviewed_by=principal.user_id,
                    note=note,
                )
            )
            audit(
                session,
                payment.tenant_id,
                "payment",
                payment.id,
                "investigation_reviewed",
                principal.user_id,
                investigation_id=str(record.id),
                evidence_digest=record.evidence_digest,
            )
            await session.flush()
        return await serialize_investigation(session, record)


async def remember_investigation(session, principal, investigation_id, client, settings):
    if not settings.breeth_configured:
        raise AppError(503, "breeth_not_configured", "Breeth advisory memory is not configured.")
    async with transaction(session, principal):
        record = await require_reviewed_investigation(session, principal, investigation_id)
        operation = await session.scalar(
            select(MemoryOperation).where(MemoryOperation.investigation_id == record.id)
        )
        if operation:
            return {
                "status": "unknown" if operation.status == "pending" else operation.status,
                "operation_id": operation.id,
                "advisory": True,
            }
        content = safe_review_summary(record)
        operation = MemoryOperation(
            id=uuid4(),
            tenant_id=principal.tenant.id,
            investigation_id=record.id,
            status="pending",
            redacted_content=content,
            provenance={
                "investigation_id": str(record.id),
                "evidence_digest": record.evidence_digest,
                "document_ids": record.document_ids,
                "provider": "breeth",
            },
        )
        session.add(operation)
        await session.flush()
        operation_id, payment_id = operation.id, record.payment_id
        audit(
            session,
            principal.tenant.id,
            "payment",
            payment_id,
            "memory_write_started",
            principal.user_id,
            operation_id=str(operation_id),
        )
    receipt = None
    try:
        receipt = await write_memory(
            client, settings, principal.tenant.id, investigation_id, content
        )
        status = "written"
    except Exception:
        status = "unknown"  # Non-idempotent write may have committed; never retry it blindly.
    async with transaction(session, principal):
        await payment_rows(session, payment_id, principal.tenant.id, lock=True)
        operation = await session.scalar(
            select(MemoryOperation)
            .where(MemoryOperation.id == operation_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if operation.status == "pending":
            operation.status, operation.provider_receipt = status, receipt
            audit(
                session,
                principal.tenant.id,
                "payment",
                payment_id,
                "memory_" + status,
                principal.user_id,
                operation_id=str(operation_id),
            )
            await session.flush()
        return {"status": operation.status, "operation_id": operation.id, "advisory": True}
