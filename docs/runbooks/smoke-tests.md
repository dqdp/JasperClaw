# Runbook: Smoke Tests

## Purpose

Provide a minimal post-deploy validation set.

## Principle

Smoke tests should confirm the canonical request path:

`Open WebUI -> agent-api -> internal runtime/services`

## Automated baseline

For the host-local automated baseline used by the deploy script, run:

```bash
COMPOSE_OVERRIDE_FILE=infra/compose/compose.prod.yml bash infra/scripts/smoke.sh
```

That script checks:

- host-local reverse proxy response through Caddy when `DOMAIN` is configured
- `agent-api` readiness from inside the container
- `GET /v1/models`
- a simple `POST /v1/chat/completions` request through the canonical backend path

The rest of this document is still the broader manual checklist to use after the automated baseline passes.

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
- if `readyz` fails for storage, confirm the explicit migration step completed before traffic was sent to `agent-api`

### 4. Chat path works

Execute a simple prompt through the UI or through the OpenAI-compatible endpoint.

If using the OpenAI-compatible endpoint directly, include `Authorization: Bearer <INTERNAL_OPENAI_API_KEY>`.

Expected result:

- streamed or non-streamed response returns successfully
- response comes through canonical backend path

### 5. Model listing works

Confirm `GET /v1/models` exposes expected logical profiles, for example:

- `assistant-v1`
- `assistant-fast`

If this check is performed directly against `agent-api`, include `Authorization: Bearer <INTERNAL_OPENAI_API_KEY>`.

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
- the explicit migration command completed successfully before smoke started
- no connection failures appear in logs

## Pass/fail rule

A deployment passes smoke if:

- user chat works
- `agent-api` liveness and readiness are both correct
- storage is functional
- at least one tool path works if tools are enabled in that environment
- speech path works if speech is enabled in that environment
