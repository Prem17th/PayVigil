import base64
import json
import sys
from io import BytesIO
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from app.core.errors import AppError
from app.evidence.config import EvidenceSettings
from app.evidence.pdf_extract import parse_pdf
from app.evidence.providers import (
    bounded_raw,
    deterministic_compare,
    extract_document,
    retrieve_memory,
    run_investigation_agent,
    safe_review_summary,
    tenant_memory_group,
    validated_result,
    write_memory,
)


def fixture_case():
    source = "invoice_reference: INV-1\namount_minor: 10000\ncurrency: INR\nsandbox_account_id: SIM-TEST-001"
    documents = [
        {
            "id": str(uuid4()),
            "filename": "synthetic.txt",
            "revision_id": str(uuid4()),
            "pages": [{"page": 1, "text": source}],
        }
    ]
    snapshot = {
        "invoice_reference": "INV-1",
        "amount_minor": 10000,
        "currency": "INR",
        "sandbox_account_id": "SIM-TEST-001",
    }
    result = {
        "summary": "The explicit fields match. Independent verification remains required.",
        "findings": [
            {
                "severity": "info",
                "code": "no_discrepancy",
                "explanation": "Explicit values match this snapshot.",
                "citations": [
                    {"document_id": documents[0]["id"], "page": 1, "quote": "amount_minor: 10000"}
                ],
            }
        ],
    }
    return snapshot, documents, result


def response_script(documents, result, *, forbidden=False):
    calls = []

    def handler(request):
        assert str(request.url) == "https://api.openai.com/v1/responses"
        body = json.loads(request.content)
        assert body["store"] is False and body["parallel_tool_calls"] is False
        assert all(tool["strict"] for tool in body["tools"])
        calls.append(body)
        order = [
            ("get_case_snapshot", {}),
            ("compare_payment_fields", {}),
            ("read_document", {"document_id": documents[0]["id"], "page": 1}),
        ]
        if len(calls) <= 3:
            name, args = order[len(calls) - 1]
            if forbidden:
                name = "execute_payment"
            output = [
                {
                    "type": "function_call",
                    "call_id": f"call_{len(calls)}",
                    "name": name,
                    "arguments": json.dumps(args),
                }
            ]
        else:
            output = [
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": json.dumps(result)}],
                }
            ]
        return httpx.Response(
            200,
            stream=httpx.ByteStream(json.dumps({"status": "completed", "output": output}).encode()),
        )

    return handler, calls


async def test_agent_chooses_scoped_tools_and_returns_grounded_result():
    snapshot, documents, result = fixture_case()
    handler, calls = response_script(documents, result)
    settings = EvidenceSettings(
        _env_file=None, openai_api_key="synthetic-openai-key", openai_model="synthetic-model"
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        actual, trace = await run_investigation_agent(
            client, settings, uuid4(), snapshot, documents
        )
    assert actual == result
    assert [t["tool"] for t in trace] == [
        "get_case_snapshot",
        "compare_payment_fields",
        "read_document",
    ]
    assert len(calls) == 4
    assert any(item.get("type") == "function_call_output" for item in calls[-1]["input"])


async def test_agent_rejects_forbidden_payment_tool_and_fabricated_citations():
    snapshot, documents, result = fixture_case()
    settings = EvidenceSettings(
        _env_file=None, openai_api_key="synthetic-key", openai_model="synthetic-model"
    )
    handler, _ = response_script(documents, result, forbidden=True)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ValueError, match="Forbidden tool"):
            await run_investigation_agent(client, settings, uuid4(), snapshot, documents)
    result["findings"][0]["citations"][0]["quote"] = "The supplier approved everything."
    with pytest.raises(ValueError, match="Ungrounded citation"):
        validated_result(result, documents, deterministic_compare(snapshot, documents))


def test_deterministic_mismatch_cannot_be_omitted_and_budget_overflow_is_explicit():
    snapshot, documents, result = fixture_case()
    documents[0]["pages"][0]["text"] += "\namount_minor: 99999"
    checked = validated_result(result, documents, deterministic_compare(snapshot, documents))
    assert any(
        f["code"] == "amount_mismatch" and f["severity"] == "critical" for f in checked["findings"]
    )
    documents[0]["pages"][0]["text"] += "\n" + "amount_minor: 10000\n" * 100
    compared = deterministic_compare(snapshot, documents)
    assert compared["coverage_incomplete"] is True
    checked = validated_result(result, documents, compared)
    assert any(f["code"] == "manual_verification_required" for f in checked["findings"])
    assert len(checked["findings"]) <= 20


async def test_unconfigured_agent_and_memory_make_no_provider_calls():
    def forbidden(_):
        pytest.fail("Unconfigured provider was called")

    snapshot, documents, _ = fixture_case()
    async with httpx.AsyncClient(transport=httpx.MockTransport(forbidden)) as client:
        with pytest.raises(AppError, match="openai_not_configured"):
            await run_investigation_agent(
                client, EvidenceSettings(_env_file=None), uuid4(), snapshot, documents
            )
        with pytest.raises(AppError, match="breeth_not_configured"):
            await retrieve_memory(client, EvidenceSettings(_env_file=None), uuid4())


async def test_utf8_extraction_and_unreadable_pdf_rejection():
    raw, pages = await extract_document(
        base64.b64encode(b"Synthetic amount_minor: 100").decode(), "text/plain"
    )
    assert pages == [{"page": 1, "text": raw.decode()}]
    for content in (b"\xff\xfe", b"\x00secret", b""):
        with pytest.raises(AppError):
            await extract_document(base64.b64encode(content).decode(), "text/plain")
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    buffer = BytesIO()
    writer.write(buffer)
    with pytest.raises(ValueError):
        parse_pdf(buffer.getvalue())
    with pytest.raises(AppError, match="unsupported_pdf|pdf_resource_limits_unavailable"):
        await extract_document(base64.b64encode(buffer.getvalue()).decode(), "application/pdf")


def synthetic_text_pdf():
    writer = PdfWriter()
    page = writer.add_blank_page(width=200, height=100)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})}
    )
    content = DecodedStreamObject()
    content.set_data(b"BT /F1 12 Tf 10 50 Td (Synthetic amount_minor: 10001) Tj ET")
    page[NameObject("/Contents")] = writer._add_object(content)
    buffer = BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def test_synthetic_text_pdf_parsing():
    assert "amount_minor: 10001" in parse_pdf(synthetic_text_pdf())[0]["text"]


@pytest.mark.skipif(
    not sys.platform.startswith("linux"),
    reason="Protected PDF child test requires Linux; this macOS host rejects memory resource limits.",
)
async def test_text_pdf_is_extracted_inside_bounded_child_process():
    raw = synthetic_text_pdf()
    original, pages = await extract_document(base64.b64encode(raw).decode(), "application/pdf")
    assert original == raw and "amount_minor: 10001" in pages[0]["text"]


async def test_encoded_or_oversize_provider_response_is_rejected_before_json_parsing():
    encoded = httpx.Response(
        200, headers={"Content-Encoding": "gzip"}, stream=httpx.ByteStream(b"compressed payload")
    )
    with pytest.raises(ValueError, match="Compressed"):
        await bounded_raw(encoded, 100)
    oversized = httpx.Response(200, stream=httpx.ByteStream(b"x" * 101))
    with pytest.raises(ValueError, match="size limit"):
        await bounded_raw(oversized, 100)


async def test_breeth_sdk_contract_scopes_group_and_exports_only_finite_review_text():
    tenant_id = uuid4()
    record = SimpleNamespace(
        summary="Personal name alice@example.invalid SIM-SECRET-999 123456789012",
        findings=[
            {
                "code": "amount_mismatch",
                "explanation": "Secret private name",
                "citations": [{"quote": "private"}],
            }
        ],
    )
    content = safe_review_summary(record)
    assert not any(word in content for word in ("alice", "SIM-SECRET", "123456", "private"))
    settings = EvidenceSettings(_env_file=None, breeth_api_key="synthetic-memory-key")

    def handler(request):
        assert request.url.host == "api.thebreeth.com"
        body = json.loads(request.content)
        assert body["group_id"] == tenant_memory_group(tenant_id)
        if request.url.path.endswith("/episodes"):
            assert body["content"] == content and body["extract_intent"] is False
            payload = {
                "ok": True,
                "episode_name": "synthetic-receipt",
                "group_id": body["group_id"],
                "extracted": {"entities": 1, "edges": 1},
            }
        else:
            payload = {
                "edges": [
                    {
                        "source_node": "review",
                        "target_node": "lesson",
                        "fact": "Verify evidence before approval.",
                        "_tier": "hot",
                    }
                ],
                "_cache": {
                    "tier": "hot",
                    "hot_hits": 1,
                    "cold_hits": 0,
                    "group_id": body["group_id"],
                },
            }
        return httpx.Response(200, stream=httpx.ByteStream(json.dumps(payload).encode()))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        assert (
            await write_memory(client, settings, tenant_id, uuid4(), content) == "synthetic-receipt"
        )
        items = await retrieve_memory(client, settings, tenant_id)
        assert items[0]["advisory"] is True
