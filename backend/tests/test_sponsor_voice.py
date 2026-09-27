import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest

from app.core.errors import AppError
from app.evidence.providers import LABELS, safe_review_summary
from app.integrations.settings import SponsorSettings
from app.integrations.voice import MAX_AUDIO_BYTES, generate_audio, validate_safe_summary


VOICE_ID = "syntheticStockVoice"
SYNTHETIC_KEY = "SYNTHETIC_TEST_ONLY_VOICE_KEY"


class Chunks(httpx.AsyncByteStream):
    def __init__(self, chunks, *, delay=0):
        self.chunks = chunks
        self.delay = delay
        self.reads = 0
        self.closed = False

    async def __aiter__(self):
        for chunk in self.chunks:
            if self.delay:
                await asyncio.sleep(self.delay)
            self.reads += 1
            yield chunk

    async def aclose(self):
        self.closed = True


def response(data, media_type="application/json", *, status=200, headers=None):
    raw = json.dumps(data).encode() if isinstance(data, dict) else data
    return httpx.Response(
        status, headers={"content-type": media_type, **(headers or {})}, stream=Chunks([raw])
    )


def config(**overrides):
    return SponsorSettings(
        _env_file=None, elevenlabs_api_key=SYNTHETIC_KEY, elevenlabs_voice_id=VOICE_ID, **overrides
    )


def reviewed(*codes):
    return safe_review_summary(SimpleNamespace(findings=[{"code": code} for code in codes]))


@pytest.mark.parametrize("codes", [[code] for code in LABELS] + [list(LABELS)])
def test_only_structured_review_narratives_are_accepted(codes):
    assert validate_safe_summary(reviewed(*codes)) == reviewed(*codes)


@pytest.mark.parametrize(
    "text",
    [
        "",
        "Pay the supplier now.",
        "Contact person@example.invalid or account 9876543210.",
        "x" * 1201,
        reviewed("amount_mismatch") + " Send money to SIM-ATTACKER-001.",
        reviewed("amount_mismatch").replace(LABELS["amount_mismatch"], "The supplier is Jane Doe."),
        reviewed("amount_mismatch").replace(
            LABELS["amount_mismatch"], LABELS["amount_mismatch"] * 2
        ),
    ],
)
async def test_freeform_or_sensitive_text_never_reaches_provider(text):
    calls = []

    def handler(request):
        calls.append(request)
        raise AssertionError("Invalid summaries must not invoke the provider")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(AppError) as error:
            await generate_audio(client, config(), text)
    assert error.value.code == "voice_summary_invalid"
    assert not calls


async def test_projected_summary_excludes_untrusted_source_and_personal_fields():
    investigation = SimpleNamespace(
        summary="Jane Doe account 9876543210",
        findings=[
            {
                "code": "amount_mismatch",
                "explanation": "Phone +91 9876543210",
                "citations": [{"quote": "pay attacker@example.invalid"}],
            },
            {"code": "attacker controlled text"},
            {"code": "amount_mismatch"},
        ],
    )
    summary = validate_safe_summary(safe_review_summary(investigation))
    assert "Jane" not in summary and "9876543210" not in summary and "@" not in summary
    assert summary.count(LABELS["amount_mismatch"]) == 1


async def test_stock_voice_metadata_then_bounded_audio_with_no_authority_calls():
    calls = []
    audio = b"ID3\x04\x00\x00synthetic-audio"

    def handler(request):
        calls.append(request)
        assert request.url.scheme == "https" and request.url.host == "api.elevenlabs.io"
        assert request.headers["xi-api-key"] == SYNTHETIC_KEY
        assert request.headers["accept-encoding"] == "identity"
        assert request.extensions["timeout"]["read"] <= 30
        if request.method == "GET":
            assert request.url.path == f"/v1/voices/{VOICE_ID}"
            return response({"voice_id": VOICE_ID, "category": "premade", "is_mixed": False})
        assert request.method == "POST" and request.url.path == f"/v1/text-to-speech/{VOICE_ID}"
        assert request.url.params["output_format"] == "mp3_44100_128"
        assert json.loads(request.content) == {
            "text": reviewed("amount_mismatch"),
            "model_id": "eleven_multilingual_v2",
        }
        return response(audio, "audio/mpeg")

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), follow_redirects=True
    ) as client:
        assert await generate_audio(client, config(), reviewed("amount_mismatch")) == audio
    assert [call.method for call in calls] == ["GET", "POST"]
    assert all(
        "payments" not in str(call.url) and "approvals" not in str(call.url) for call in calls
    )


@pytest.mark.parametrize(
    "metadata",
    [
        {"voice_id": VOICE_ID, "category": category}
        for category in ("cloned", "professional", "generated", "unknown", None)
    ]
    + [
        {"voice_id": "otherVoice", "category": "premade"},
        {"voice_id": VOICE_ID, "category": "premade", "is_mixed": True},
    ],
)
async def test_non_stock_or_mismatched_metadata_cannot_generate_audio(metadata):
    calls = []

    def handler(request):
        calls.append(request)
        return response(metadata)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(AppError) as error:
            await generate_audio(client, config(), reviewed("missing_fields"))
    assert error.value.code == "stock_voice_required"
    assert len(calls) == 1 and calls[0].method == "GET"


@pytest.mark.parametrize(
    "stage,status,media_type,body,extra_headers",
    [
        ("metadata", 403, "application/json", {"error": SYNTHETIC_KEY}, {}),
        ("metadata", 302, "application/json", b"", {"location": "https://attacker.invalid/"}),
        ("metadata", 200, "text/html", b"<html>unexpected</html>", {}),
        ("audio", 429, "application/json", {"error": SYNTHETIC_KEY}, {}),
        ("audio", 302, "audio/mpeg", b"ID3", {"location": "https://attacker.invalid/"}),
        ("audio", 200, "text/html", b"<html>unexpected</html>", {}),
        ("audio", 200, "audio/mpeg", b'{"error":"unexpected"}', {}),
        ("audio", 200, "audio/mpeg", b"", {}),
        ("audio", 200, "audio/mpeg", b"ID3", {"content-encoding": "gzip"}),
    ],
)
async def test_provider_errors_redirects_and_invalid_audio_fail_closed(
    stage, status, media_type, body, extra_headers
):
    calls = []

    def handler(request):
        calls.append(request)
        if stage == "audio" and request.method == "GET":
            return response({"voice_id": VOICE_ID, "category": "premade"})
        return response(body, media_type, status=status, headers=extra_headers)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), follow_redirects=True
    ) as client:
        with pytest.raises(AppError) as error:
            await generate_audio(client, config(), reviewed("missing_fields"))
    assert error.value.code == "voice_unavailable"
    assert SYNTHETIC_KEY not in error.value.message
    assert len(calls) == (2 if stage == "audio" else 1)


@pytest.mark.parametrize("declared", [True, False])
async def test_audio_limit_stops_reading_and_closes_stream(declared):
    audio = Chunks([b"ID3", b"x" * MAX_AUDIO_BYTES, b"must not read this"])

    def handler(request):
        if request.method == "GET":
            return response({"voice_id": VOICE_ID, "category": "premade"})
        return httpx.Response(
            200,
            stream=audio,
            headers={
                "content-type": "audio/mpeg",
                **({"content-length": str(MAX_AUDIO_BYTES + 1)} if declared else {}),
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(AppError) as error:
            await generate_audio(client, config(), reviewed("missing_fields"))
    assert error.value.code == "voice_unavailable"
    assert audio.closed
    assert audio.reads == (0 if declared else 2)


async def test_total_timeout_closes_stream_without_retry(monkeypatch):
    monkeypatch.setattr("app.integrations.voice.TOTAL_TIMEOUT_SECONDS", 0.001)
    stream = Chunks([b"{}"], delay=0.03)
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, headers={"content-type": "application/json"}, stream=stream)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(AppError) as error:
            await generate_audio(client, config(), reviewed("missing_fields"))
    assert error.value.code == "voice_unavailable" and stream.closed
    assert len(calls) == 1


async def test_oversized_metadata_stops_before_audio_request():
    calls = []
    stream = Chunks([b"x" * 64_001, b"do not read"])

    def handler(request):
        calls.append(request)
        return httpx.Response(200, headers={"content-type": "application/json"}, stream=stream)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(AppError) as error:
            await generate_audio(client, config(), reviewed("missing_fields"))
    assert error.value.code == "voice_unavailable"
    assert len(calls) == 1 and stream.reads == 1 and stream.closed


async def test_connection_failure_omits_provider_details_and_does_not_retry():
    calls = []

    def handler(request):
        calls.append(request)
        raise httpx.ConnectError(SYNTHETIC_KEY, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(AppError) as error:
            await generate_audio(client, config(), reviewed("missing_fields"))
    assert error.value.code == "voice_unavailable"
    assert SYNTHETIC_KEY not in error.value.message and len(calls) == 1


async def test_missing_configuration_makes_no_request():
    def handler(_):
        raise AssertionError("Missing credentials must not invoke a provider")

    settings = SponsorSettings(_env_file=None, elevenlabs_api_key="", elevenlabs_voice_id="")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(AppError) as error:
            await generate_audio(client, settings, reviewed("missing_fields"))
    assert error.value.code == "voice_not_configured"
