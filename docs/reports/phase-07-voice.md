# Phase 7 — spoken investigation explanations

The local voice adapter and frontend playback are implemented. Real ElevenLabs
generation and playback remain unverified because provider credentials are
deferred. All checks in this report use controlled test transports.

## Implemented behavior

- `backend/app/sponsor_voice.py` exports `generate_audio(client, settings,
  summary)`. The caller must authorize a current, human-reviewed investigation.
  The adapter accepts only the exact finite grammar produced by
  `evidence_providers.safe_review_summary`, using the shared finding-label map.
  Names, account details, contact details, source quotations, human notes, and
  arbitrary model summaries cannot enter the narration through this interface.
- Narration is limited to 1,200 characters and explicitly preserves the human
  approval boundary. This is a categorical explanation of reviewed findings;
  the visual workspace remains the place to inspect the full cited evidence.
- Before generation, the adapter reads the configured voice's metadata from
  the fixed official origin. The returned ID must match, its category must be
  `premade`, and mixed voices are rejected. Cloned, generated, professional,
  missing, or unrecognized categories fail closed.
- A single bounded operation performs metadata lookup and text-to-speech.
  It permits no redirects, requests identity encoding, limits metadata to
  64,000 bytes and raw audio to 2,000,000 bytes, and enforces a 35-second total
  timeout. Audio must have an MP3 content type and signature. The signature is
  a format sanity check, not a complete audio decoder.
- Credentials are read from `ELEVENLABS_API_KEY` and `ELEVENLABS_VOICE_ID`.
  Provider response bodies are excluded from public failures. There is no
  automatic retry and no identity, supplier-confirmation, or payment authority.
- The frontend fetches audio through the authenticated application route,
  provides manual playback, aborts waiting on unmount, and revokes Blob URLs on
  replacement and unmount. Text and payment controls remain available if audio
  is unavailable.

## Verification

`backend/tests/test_sponsor_voice.py` covers structured narration, exclusion of
freeform/sensitive text, stock voice identity and category, request scope,
redirect rejection, provider failures, content types, empty/invalid audio,
streamed and declared size limits, oversized metadata, cleanup, total timeout,
and missing credentials. Tests use `httpx.MockTransport` and synthetic streams;
they do not generate real speech or establish provider availability.

Result: `python -m pytest tests/test_sponsor_voice.py -q` — **41 passed**.

The frontend's boundary suite and production build also pass. The audio route's
tenant, finance-role, current-snapshot, and review checks belong to the integrated
backend verification; this pure adapter test suite does not establish them.

## Primary references checked on 2026-09-27

ElevenLabs documents text-to-speech as a POST to the selected voice, with an
`xi-api-key` header, text/model fields, and MP3 output. The adapter uses the
documented `eleven_multilingual_v2` model and `mp3_44100_128` format.
[Create speech](https://elevenlabs.io/docs/api-reference/text-to-speech/convert)

Voice metadata includes the voice ID and category. The list endpoint explicitly
distinguishes `premade`, `cloned`, `generated`, and `professional` categories.
[Get voice](https://elevenlabs.io/docs/api-reference/voices/get),
[List voices](https://elevenlabs.io/docs/api-reference/voices/search)

## Remaining checks

Supply managed server credentials for a stock voice with permission to read its
metadata and generate speech. Then verify a real reviewed-case request, audio
playback, failure behavior, and deployed role isolation. Provider retention and
account permissions depend on the configured ElevenLabs account; no zero
retention claim is made. Continue the already-authorized remaining local build
and integration checks; no intermediate approval gate is required.
