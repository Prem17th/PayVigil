import asyncio
import base64

import httpx
import pytest
from sqlalchemy import select

from app.evidence import domain as evidence
from app.payments import domain as payments
from app.core.errors import AppError
from app.evidence.config import EvidenceSettings
from app.evidence.models import EvidenceDocument, MemoryOperation
from app.evidence.schemas import EvidenceUpload
from test_evidence_providers import response_script
from test_payment_domain import payment_db as payment_db
from test_payment_domain import prepare_payment, call, decision, queue


SOURCE = "invoice_reference: INV-001\namount_minor: 10001\ncurrency: INR\nsandbox_account_id: SIM-SUPPLIER-001"


class EvidenceStorage:
    def __init__(self):
        self.objects = {}
        self.posts = 0
        self.corrupt = False

    def __call__(self, request):
        path = request.url.path
        if "/bucket/" in path:
            return httpx.Response(200, json={"public": False})
        if request.method == "POST":
            self.posts += 1
            self.objects[path] = request.content
            return httpx.Response(200, json={"Key": path})
        if "/object/authenticated/" in path:
            key = path.replace("/object/authenticated/", "/object/")
            if key not in self.objects:
                return httpx.Response(404)
            return httpx.Response(
                200,
                stream=httpx.ByteStream(
                    b"corrupted original" if self.corrupt else self.objects[key]
                ),
            )
        return httpx.Response(403)


async def upload(db, payment, client, settings, text=SOURCE):
    body = EvidenceUpload(
        revision_id=payment.current_revision.id,
        filename="synthetic.txt",
        media_type="text/plain",
        content_base64=base64.b64encode(text.encode()).decode(),
    )
    async with db.api() as session:
        return await evidence.upload_evidence(
            session, db.finance, payment.id, body, client, settings
        )


def agent_provider(document_id, revision_id, text=SOURCE):
    documents = [
        {
            "id": str(document_id),
            "revision_id": str(revision_id),
            "filename": "synthetic.txt",
            "pages": [{"page": 1, "text": text}],
        }
    ]
    result = {
        "summary": "Review the exact payment and supplied evidence.",
        "findings": [
            {
                "severity": "info",
                "code": "no_discrepancy",
                "explanation": "The explicitly labelled values match.",
                "citations": [
                    {"document_id": str(document_id), "page": 1, "quote": "amount_minor: 10001"}
                ],
            }
        ],
    }
    return response_script(documents, result)[0]


async def investigate(db, payment, client):
    settings = EvidenceSettings(
        _env_file=None, openai_api_key="synthetic-model-key", openai_model="synthetic-model"
    )
    async with db.api() as session:
        return await evidence.investigate(
            session, db.finance, payment.id, payment.current_revision.id, client, settings
        )


async def review(db, investigation_id):
    async with db.api() as session:
        return await evidence.review_investigation(
            session,
            db.finance,
            investigation_id,
            "Synthetic human acknowledgement; independent verification still required.",
        )


async def test_new_evidence_invalidates_review_and_exact_approval(payment_db, settings):
    db = payment_db
    payment = await prepare_payment(db, approved=True)
    storage = EvidenceStorage()
    async with httpx.AsyncClient(transport=httpx.MockTransport(storage)) as client:
        document = await upload(db, payment, client, settings)
    assert document["extraction_status"] == "extracted"
    with pytest.raises(AppError, match="evidence_review_required"):
        await queue(db, payment)
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(agent_provider(document["id"], payment.current_revision.id))
    ) as client:
        result = await investigate(db, payment, client)
    assert result["status"] == "completed" and result["is_current"] is True
    await review(db, result["id"])
    with pytest.raises(AppError, match="approval_required"):
        await queue(db, payment)  # Old financial approval cannot authorize new evidence.
    approved = await call(db, payments.approve_payment, payment.id, decision(payment))
    assert approved.approval.id != payment.approval.id
    async with httpx.AsyncClient(transport=httpx.MockTransport(storage)) as client:
        await upload(
            db,
            payment,
            client,
            settings,
            SOURCE + "\nChanged instruction: sandbox_account_id: SIM-OTHER-999",
        )
    with pytest.raises(AppError, match="stale_investigation"):
        await review(db, result["id"])
    with pytest.raises(AppError, match="evidence_review_required"):
        await queue(db, approved)
    async with db.api() as session:
        records = await evidence.list_investigations(session, db.finance, payment.id)
    assert records["investigations"][0]["is_current"] is False


async def test_pending_upload_blocks_queue_and_unknown_upload_only_reads_back(payment_db, settings):
    db = payment_db
    payment = await prepare_payment(db, approved=True)
    storage = EvidenceStorage()
    posted = asyncio.Event()
    release = asyncio.Event()

    async def handler(request):
        if request.method == "POST":
            posted.set()
            await release.wait()
        return storage(request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        pending = asyncio.create_task(upload(db, payment, client, settings))
        await asyncio.wait_for(posted.wait(), 2)
        with pytest.raises(AppError, match="evidence_review_required"):
            await queue(db, payment)
        storage.corrupt = True
        release.set()
        with pytest.raises(AppError, match="evidence_upload_unknown"):
            await pending
        with pytest.raises(AppError, match="evidence_upload_unknown"):
            await upload(db, payment, client, settings)
        assert storage.posts == 1
        storage.corrupt = False
        verified = await upload(db, payment, client, settings)
        assert verified["extraction_status"] == "extracted" and storage.posts == 1


async def test_unknown_memory_write_is_durable_redacted_and_never_blindly_retried(
    payment_db, settings
):
    db = payment_db
    payment = await prepare_payment(db)
    storage = EvidenceStorage()
    async with httpx.AsyncClient(transport=httpx.MockTransport(storage)) as client:
        document = await upload(db, payment, client, settings)
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(agent_provider(document["id"], payment.current_revision.id))
    ) as client:
        result = await investigate(db, payment, client)
    await review(db, result["id"])
    calls = []

    def uncertain(request):
        calls.append(request)
        raise httpx.ReadTimeout("synthetic lost response", request=request)

    memory_settings = EvidenceSettings(_env_file=None, breeth_api_key="synthetic-memory-key")
    async with httpx.AsyncClient(transport=httpx.MockTransport(uncertain)) as client:
        async with db.api() as session:
            first = await evidence.remember_investigation(
                session, db.finance, result["id"], client, memory_settings
            )
        async with db.api() as session:
            second = await evidence.remember_investigation(
                session, db.finance, result["id"], client, memory_settings
            )
    assert first == second and first["status"] == "unknown" and len(calls) == 1
    async with db.admin() as session:
        operation = await session.get(MemoryOperation, first["operation_id"])
        assert (
            "SIM-SUPPLIER" not in operation.redacted_content
            and "INV-001" not in operation.redacted_content
        )
        assert operation.provenance["investigation_id"] == str(result["id"])


async def test_concurrent_investigation_reuses_durable_running_operation(
    payment_db, settings, monkeypatch
):
    db = payment_db
    payment = await prepare_payment(db)
    async with httpx.AsyncClient(transport=httpx.MockTransport(EvidenceStorage())) as client:
        document = await upload(db, payment, client, settings)
    started = asyncio.Event()
    release = asyncio.Event()
    calls = []

    async def controlled_agent(*args):
        calls.append(1)
        started.set()
        await release.wait()
        return {"summary": "Synthetic contract result", "findings": []}, []

    monkeypatch.setattr(evidence, "run_investigation_agent", controlled_agent)
    async with httpx.AsyncClient() as client:
        pending = asyncio.create_task(investigate(db, payment, client))
        await asyncio.wait_for(started.wait(), 2)
        second = await investigate(db, payment, client)
        assert second["status"] == "running"
        release.set()
        first = await pending
    assert first["id"] == second["id"] and len(calls) == 1
    async with db.api() as session:
        with pytest.raises(AppError) as denied:
            await evidence.read_original(session, db.outsider, document["id"], None, settings)
    assert denied.value.status == 404
    async with db.api() as session, payments.transaction(session, db.supplier):
        assert (await session.scalars(select(EvidenceDocument))).all() == []
