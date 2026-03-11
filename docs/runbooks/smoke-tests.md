# Runbook: Smoke Tests

## Purpose

Provide a minimal post-deploy validation set.

## Principle

Smoke tests should confirm the canonical request path:

`Open WebUI -> agent-api -> internal runtime/services`

## Required checks

### 1. Reverse proxy reachable

- HTTPS endpoint responds
- valid certificate is presented
- WebSocket upgrade is not broken

### 2. Open WebUI reachable

- login page loads
- authenticated session works
- no visible frontend errors on basic chat load

### 3. agent-api healthy

- `GET /healthz` returns success as a liveness check
- `GET /readyz` returns success for the core text path

### 4. Chat path works

Execute a simple prompt through the UI or through the OpenAI-compatible endpoint.

Expected result:

- streamed or non-streamed response returns successfully
- response comes through canonical backend path

### 5. Model listing works

Confirm `GET /v1/models` exposes expected logical profiles, for example:

- `assistant-v1`
- `assistant-fast`

### 6. Ollama path works indirectly

Confirm a chat response can be generated through `agent-api`.

Do not validate Ollama by treating it as the primary public API.

### 7. STT path works

Submit a short known audio sample.

Expected result:

- transcription succeeds
- language is plausible
- latency is acceptable for v1 expectations

Run this only if voice is enabled in that environment.

### 8. TTS path works

Submit a short text payload.

Expected result:

- audio file or stream is returned
- chosen voice resolves correctly

Run this only if voice is enabled in that environment.

### 9. Tool path works

Run at least one safe tool request, for example web search.

Expected result:

- tool call succeeds
- response is routed through agent-api/tool boundary correctly

Run this only if tool adapters are enabled in that environment.

### 10. Database-backed state path works

Confirm:

- agent-api can read/write required state
- no migration errors are present
- no connection failures appear in logs

## Pass/fail rule

A deployment passes smoke if:

- user chat works
- `agent-api` liveness and readiness are both correct
- storage is functional
- at least one tool path works if tools are enabled in that environment
- speech path works if speech is enabled in that environment
