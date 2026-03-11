# agent-api Service Contract

## Purpose

`agent-api` is the canonical backend ingress for all user-facing assistant traffic.

It provides an OpenAI-compatible facade for `Open WebUI` and orchestrates calls to internal runtime services.

## Responsibilities

- expose OpenAI-compatible endpoints
- normalize text and voice requests
- apply profile routing and request policy
- read and write canonical state
- invoke internal runtime dependencies
- emit audit and operational telemetry

## Non-responsibilities

- direct public UI hosting
- long-running autonomous workflows in v1
- exposing raw internal model IDs to clients
- exposing provider-specific tool adapters directly to clients

## Upstream clients

- `Open WebUI`
- future mobile or PWA clients
- future CLI or automation clients

## Downstream dependencies

- `Ollama`
- `Postgres`
- `stt-service` when the voice path is enabled
- `tts-service` when the voice path is enabled
- typed tools integration layer inside `agent-api` in v1

## Model exposure

The public API must expose logical assistant profiles, not raw runtime model names.

### Public model IDs

- `assistant-v1`
- `assistant-fast`

### Routing rule

- `assistant-v1` maps to the default high-quality assistant profile
- `assistant-fast` maps to the lower-latency profile
- internal model names are implementation details and must not leak into the public contract
- no automatic per-request fallback is performed in v1

## Public endpoints

### `GET /healthz`

Liveness probe.

Meaning:

- process is alive
- service can answer a basic liveness request
- downstream dependency failures must not make this probe fail

Response:

```json
{ "status": "ok" }
```

### `GET /readyz`

Readiness probe.

Readiness must reflect:

- core text-path readiness, not just process liveness
- internal config validity
- database connectivity
- primary `Ollama` runtime availability for active chat profiles

Readiness must not fail only because:

- an optional tool adapter is unavailable
- `stt-service` or `tts-service` is unavailable while voice is not enabled as a required deployment feature

Recommended response behavior:

- `200` when the service can accept core text traffic
- `503` when the core text path is not ready

Success response:

```json
{ "status": "ready" }
```

Failure response example:

```json
{
  "status": "not_ready",
  "checks": {
    "config": "ok",
    "postgres": "ok",
    "ollama": "fail"
  }
}
```

### `GET /v1/models`

List available logical assistant profiles.

Response shape:

```json
{
  "object": "list",
  "data": [
    { "id": "assistant-v1", "object": "model", "owned_by": "local-assistant" },
    { "id": "assistant-fast", "object": "model", "owned_by": "local-assistant" }
  ]
}
```

### `POST /v1/chat/completions`

OpenAI-compatible chat endpoint.

Minimum request fields:

- `model`
- `messages`
- `stream`

Supported message roles:

- `system`
- `user`
- `assistant`
- `tool` if tool calling is enabled in the current milestone

Behavior:

- validates request schema
- resolves logical profile to internal runtime config
- optionally loads memory context
- invokes model runtime
- returns an explicit failure if the selected runtime target is unavailable
- persists request and response metadata
- returns non-streaming JSON or SSE stream

### `POST /v1/audio/transcriptions`

OpenAI-compatible transcription endpoint.

Minimum multipart fields:

- `file`
- `model`

Behavior:

- accepts uploaded audio
- forwards normalized transcription request to `stt-service`
- returns normalized OpenAI-style response

### `POST /v1/audio/speech`

OpenAI-compatible speech synthesis endpoint.

Minimum request fields:

- `model`
- `input`
- `voice`

Behavior:

- validates requested voice or profile
- forwards synthesis request to `tts-service`
- returns audio bytes with correct content type

## Error contract

Errors must be stable and machine-readable.

Response shape:

```json
{
  "error": {
    "type": "upstream_error",
    "code": "ollama_unavailable",
    "message": "Model runtime unavailable",
    "request_id": "req_123"
  }
}
```

## Required error categories

- `validation_error`
- `authentication_error`
- `authorization_error`
- `policy_error`
- `rate_limit_error`
- `upstream_error`
- `dependency_unavailable`
- `internal_error`

## Suggested stable codes

Examples of stable `code` values:

- `invalid_request`
- `missing_required_field`
- `unknown_profile`
- `unsupported_feature`
- `invalid_client_credentials`
- `tool_not_allowed`
- `voice_not_enabled`
- `database_unavailable`
- `runtime_unavailable`
- `dependency_timeout`
- `dependency_bad_response`
- `internal_failure`

## Suggested HTTP mapping

- `validation_error` -> `400` or `422`
- `authentication_error` -> `401`
- `authorization_error` -> `403`
- `policy_error` -> `403`
- `rate_limit_error` -> `429`
- `dependency_unavailable` -> `503` or `504`
- `upstream_error` -> `502`
- `internal_error` -> `500`

## Streaming contract

For `stream=true`, the endpoint must return `text/event-stream`.

Rules:

- each chunk includes `id`, `object`, and `choices`
- chunk ordering must be stable
- terminal chunk must be followed by `data: [DONE]`
- partial failures must be logged with the same `request_id`
- if a failure occurs before the first chunk, return the normal error envelope instead of a partial stream

## Persistence contract

At minimum the service must persist:

- request id
- conversation or session identifier if present
- selected logical profile
- normalized prompt and messages
- model response
- token usage when available
- upstream latency and status
- tool usage metadata when applicable

## Observability contract

Every request must produce:

- request id
- route name
- selected model or profile
- downstream dependency timings
- success or failure outcome

Recommended response behavior:

- return the request identifier in `X-Request-ID`
- preserve the same ID across logs and downstream dependency records

Minimum structured log events:

- request received
- request validated
- dependency call started
- dependency call completed
- persistence write completed
- request completed
- request failed
- readiness check completed

## Security rules

- `agent-api` is the only public AI/backend ingress
- `Open WebUI` authenticates to `agent-api` with an internal shared credential in v1
- upstream secrets stay server-side
- internal service tokens must not be exposed to `Open WebUI`
- private runtime dependencies are trusted by the network boundary in v1
- raw internal network topology is not part of the client contract

## Compatibility policy

The OpenAI-compatible surface is stable within v1 for:

- endpoint paths
- high-level request and response structure
- model profile IDs

Internal implementation details may change without client-visible contract changes.
