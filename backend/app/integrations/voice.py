"""Bounded stock-voice narration. This module has no payment or database tools."""

import asyncio
import json
from urllib.parse import quote

import httpx

from app.core.errors import AppError
from app.evidence.providers import LABELS
from app.integrations.settings import SponsorSettings

MAX_TEXT_CHARACTERS = 1200
MAX_AUDIO_BYTES = 2_000_000
MAX_METADATA_BYTES = 64_000
TOTAL_TIMEOUT_SECONDS = 35
ELEVENLABS_ORIGIN = "https://api.elevenlabs.io"

SUMMARY_PREFIX = "Reviewed advisory investigation. "
SUMMARY_SUFFIX = " Supplier confirmation and review do not prove bank-account ownership. Only authenticated finance users can approve an exact payment."


def validate_safe_summary(summary: str) -> str:
    """Accept only the finite output grammar of safe_review_summary.

    Names, identifiers, notes, source quotes and arbitrary model prose never
    satisfy this grammar, including when appended to a valid narrative.
    """
    if not isinstance(summary, str) or not summary or len(summary) > MAX_TEXT_CHARACTERS:
        raise AppError(
            422, "voice_summary_invalid", "The reviewed explanation is unavailable or too long."
        )
    invalid = AppError(
        422, "voice_summary_invalid", "Only the structured, redacted explanation can be spoken."
    )
    if not summary.startswith(SUMMARY_PREFIX) or not summary.endswith(SUMMARY_SUFFIX):
        raise invalid
    body = summary[len(SUMMARY_PREFIX) : -len(SUMMARY_SUFFIX)]
    sentences = []
    while body:
        sentence = next((value for value in LABELS.values() if body.startswith(value)), None)
        if sentence is None or sentence in sentences:
            raise invalid
        sentences.append(sentence)
        body = body[len(sentence) :]
        if body:
            if not body.startswith(" "):
                raise invalid
            body = body[1:]
    if not sentences or SUMMARY_PREFIX + " ".join(sentences) + SUMMARY_SUFFIX != summary:
        raise invalid
    return summary


def _unavailable() -> AppError:
    return AppError(
        503,
        "voice_unavailable",
        "ElevenLabs audio could not be verified. No automatic retry was made.",
    )


async def _bounded_raw(response: httpx.Response, limit: int) -> bytes:
    # Request uncompressed bytes so decompression cannot allocate an unbounded
    # body before the streamed-byte limit is enforced.
    if response.headers.get("content-encoding", "identity").lower() not in {"identity", ""}:
        raise ValueError("encoded provider response")
    length = response.headers.get("content-length")
    if length is not None and (not length.isdecimal() or int(length) > limit):
        raise ValueError("provider response size")
    result = bytearray()
    async for chunk in response.aiter_raw():
        if len(result) + len(chunk) > limit:
            raise ValueError("provider response size")
        result.extend(chunk)
    if not result:
        raise ValueError("empty provider response")
    return bytes(result)


async def generate_audio(
    client: httpx.AsyncClient, settings: SponsorSettings, summary: str
) -> bytes:
    """The caller must authorize a current human-reviewed investigation first.

    The only outbound write is text-to-speech at a fixed official origin. The
    configured voice is checked on every call; generated/cloned/professional
    voices do not satisfy the application's stock-voice requirement.
    """
    if not settings.voice_configured:
        raise AppError(503, "voice_not_configured", "ElevenLabs voice is not configured.")
    text = validate_safe_summary(summary)
    voice_id = settings.elevenlabs_voice_id
    path_id = quote(voice_id, safe="")
    headers = {
        "xi-api-key": settings.elevenlabs_api_key.get_secret_value(),
        "Accept-Encoding": "identity",
    }
    try:
        async with asyncio.timeout(TOTAL_TIMEOUT_SECONDS):
            async with client.stream(
                "GET",
                f"{ELEVENLABS_ORIGIN}/v1/voices/{path_id}",
                headers={**headers, "Accept": "application/json"},
                timeout=10,
                follow_redirects=False,
            ) as response:
                if (
                    response.status_code != 200
                    or response.headers.get("content-type", "").split(";", 1)[0].lower()
                    != "application/json"
                ):
                    raise ValueError("voice metadata unavailable")
                voice = json.loads(await _bounded_raw(response, MAX_METADATA_BYTES))
            if (
                not isinstance(voice, dict)
                or voice.get("voice_id") != voice_id
                or voice.get("category") != "premade"
                or voice.get("is_mixed") is True
            ):
                raise AppError(
                    503,
                    "stock_voice_required",
                    "The configured voice could not be verified as an unmixed stock voice.",
                )
            async with client.stream(
                "POST",
                f"{ELEVENLABS_ORIGIN}/v1/text-to-speech/{path_id}",
                params={"output_format": "mp3_44100_128"},
                headers={**headers, "Accept": "audio/mpeg"},
                json={"text": text, "model_id": "eleven_multilingual_v2"},
                timeout=30,
                follow_redirects=False,
            ) as response:
                media_type = (
                    response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                )
                if response.status_code != 200 or media_type not in {"audio/mpeg", "audio/mp3"}:
                    raise ValueError("audio response unavailable")
                audio = await _bounded_raw(response, MAX_AUDIO_BYTES)
            # A signature check rejects common HTML/JSON error bodies that were
            # incorrectly labelled audio. It is not a full MP3 decoder.
            if not (
                audio.startswith(b"ID3")
                or (len(audio) > 2 and audio[0] == 255 and audio[1] & 224 == 224)
            ):
                raise ValueError("audio signature unavailable")
            return audio
    except (httpx.HTTPError, ValueError, TimeoutError):
        raise _unavailable() from None
