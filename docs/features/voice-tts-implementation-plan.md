# Voice TTS Implementation Plan

## Purpose

Turn the agreed `Piper-compatible default + XTTS premium profile later` decision
into an executable first implementation slice.

This document defines the concrete v1 scope, test contract, file shape, and
sequencing for the first real `tts-service` delivery.

## Agreed baseline

From the current stack decision:

- `tts-service` stays a distinct internal service behind `agent-api`
- the public `agent-api` endpoint remains `POST /v1/audio/speech`
- the first shipping backend is `Piper-compatible`
- `XTTS v2` is explicitly deferred to a later premium GPU profile
- the first slice is buffered, non-streaming, and `audio/wav` only
- exactly one TTS engine is active per deployment

## Non-goals for this slice

- XTTS implementation
- streaming synthesis
- MP3/Opus/AAC response formats
- dynamic voice cloning
- per-request engine selection
- persistent storage of generated audio
- cloud-provider adapters

## Public behavior to preserve

### `agent-api`

`POST /v1/audio/speech` remains the only public synthesis endpoint.

Public expectations:

- requires the same bearer auth as other `/v1/*` routes
- accepts `model`, `input`, and optional `voice`
- returns binary `audio/wav`
- returns explicit machine-readable errors when voice is disabled or unsupported

### `tts-service`

Expose one internal endpoint:

- `POST /speak`

Internal expectations:

- validates synthesis input
- resolves the public voice ID against static configuration
- invokes the configured local engine
- returns `audio/wav`

## Proposed `tts-service` request contract

### Request body

```json
{
  "input": "Turn on the lights in the kitchen.",
  "voice": "assistant-default"
}
```

Rules:

- `input` is required
- `voice` is optional; when omitted, use `TTS_DEFAULT_VOICE`
- reject empty input
- reject input above a configured character limit

### Success response

- HTTP `200`
- body is raw `audio/wav` bytes
- `Content-Type: audio/wav`

### Failure shape

Use a stable JSON error body:

```json
{
  "error": {
    "type": "validation_error",
    "code": "unsupported_voice",
    "message": "Requested voice is not configured"
  }
}
```

Suggested internal error codes:

- `invalid_request`
- `missing_required_field`
- `unsupported_voice`
- `voice_not_enabled`
- `input_too_large`
- `runtime_busy`
- `runtime_unavailable`
- `dependency_timeout`
- `dependency_bad_response`
- `internal_failure`

## Proposed internal shape

Keep the first slice small and explicit.

### New `tts-service` modules

- `app/main.py`
  - FastAPI app and route wiring
- `app/core/config.py`
  - environment parsing
- `app/schemas.py`
  - request and error response models
- `app/services/speech.py`
  - synthesis facade
- `app/engines/base.py`
  - `TtsEngine` protocol
- `app/engines/piper.py`
  - first real local backend
- `app/voice_registry.py`
  - static voice mapping loader

### Minimal `TtsEngine` contract

Conceptually:

- `synthesize(text: str, voice_id: str) -> bytes`
- output is always WAV bytes in v1
- engine-specific model names stay inside the adapter

### Voice registry

Keep it static for v1.

Suggested shape:

```toml
[voices.assistant-default]
engine = "piper"
model = "ru_RU-irina-medium"

[voices.assistant-fast]
engine = "piper"
model = "ru_RU-irina-medium"
```

The exact file format can be `toml` or a Python dict, but:

- it must be static
- it must resolve public voice IDs deterministically
- it must not require a database

## Config surface

Keep the first slice minimal.

### Reuse existing

- `TTS_BASE_URL`
- `TTS_DEFAULT_VOICE`

### Add for `tts-service`

- `VOICE_ENABLED`
  - `true|false`
- `TTS_ENGINE`
  - default: `piper`
- `TTS_MAX_INPUT_CHARS`
  - conservative default
- `TTS_MAX_CONCURRENCY`
  - default: `1`
- `TTS_VOICE_REGISTRY_PATH`
  - path to static voice registry

### Add for Piper profile

- `PIPER_MODEL_DIR` or equivalent model location variable
- optional binary/runtime path if CLI invocation is used

## Backpressure and concurrency

Do not overdesign this.

First-slice rule:

- allow only one synthesis job at a time by default
- if the service is busy, fail explicitly rather than silently queueing deep

Recommended v1 behavior:

- return `503` with `runtime_busy` when the concurrency limit is exceeded

This is intentionally conservative.

It keeps tail latency bounded and avoids turning TTS into an implicit worker
queue before we understand load.

## `agent-api` integration shape

Keep the public router thin.

### New `agent-api` pieces

- add a small TTS client
- validate voice-enabled policy before calling downstream
- map downstream TTS errors into the existing stable error taxonomy
- preserve binary passthrough for WAV responses

Likely file touch points:

- `services/agent-api/app/api/routers/audio.py`
- `services/agent-api/app/api/deps.py`
- new internal client module for `tts-service`
- `services/agent-api/app/core/config.py`

## TDD plan

Write tests before implementation.

### Phase 1: `tts-service` contract tests

Add tests for:

- `GET /healthz` still returns `200`
- `POST /speak` with valid input returns `audio/wav`
- missing `input` fails validation
- blank `input` fails validation
- too-large `input` fails with `input_too_large`
- omitted `voice` uses `TTS_DEFAULT_VOICE`
- unknown `voice` fails with `unsupported_voice`
- disabled voice mode fails with `voice_not_enabled`
- busy service returns `runtime_busy`
- engine exception maps to stable error JSON

### Phase 2: `agent-api` route tests

Add tests for:

- `/v1/audio/speech` still requires auth
- valid request proxies to `tts-service`
- unsupported voice maps to stable public error
- `VOICE_ENABLED=false` returns `voice_not_enabled`
- successful response preserves `audio/wav`
- downstream timeout/unavailable maps to explicit dependency error

### Phase 3: integration smoke

Add one real smoke path:

- `agent-api -> tts-service -> Piper-compatible backend`
- one configured default voice
- one short Russian text sample

This smoke test should be optional or isolated so it does not burden the fast
unit suite.

## Suggested implementation order

1. Add `tts-service` config parsing and schemas.
2. Add `voice_registry` and failing tests for unknown/default voices.
3. Add `TtsEngine` protocol and a fake engine for tests.
4. Add `/speak` happy path using the fake engine.
5. Implement the real Piper-compatible adapter.
6. Add `agent-api` TTS client and route integration.
7. Add smoke coverage.

## Acceptance criteria

The first slice is done when:

- `tts-service /speak` synthesizes a real WAV file from a configured default
  voice
- `agent-api /v1/audio/speech` proxies that audio correctly
- unsupported voices and disabled voice mode fail explicitly
- one real Docker-based smoke test passes
- the text path remains unaffected when voice is disabled

## Follow-on slice after this one

Only after the Piper-default slice is stable:

- evaluate XTTS as an optional premium GPU profile
- revisit whether streaming is justified
- revisit whether additional output formats are justified
