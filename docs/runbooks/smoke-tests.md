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
- `POST /v1/audio/transcriptions` when `VOICE_ENABLED=true` in the deployment env
- `POST /v1/audio/speech` when `VOICE_ENABLED=true` in the deployment env
- Open WebUI voice wiring to `agent-api` when `VOICE_ENABLED=true` in the deployment env

The automated baseline is not a browser-driven UI test.
It validates the public `agent-api` ingress directly and, for the supported
voice profile, separately validates the effective Open WebUI runtime wiring.

The rest of this document is still the broader manual checklist to use after the automated baseline passes.

Supported profile expectations:

- `text-only`
  - `COMPOSE_PROFILES=`
  - `VOICE_ENABLED=false`
  - smoke must validate chat and model listing, but must not require STT or TTS
- `voice-enabled-cpu`
  - `COMPOSE_PROFILES=voice`
  - `VOICE_ENABLED=true`
  - smoke must validate chat, STT, and TTS through `agent-api`
  - smoke must validate Open WebUI voice wiring to the same `agent-api` ingress
  - `stt-service` is expected to prewarm its configured runtime during startup
    instead of acquiring it lazily on the first readiness call

If `VOICE_ENABLED=true` but the Compose `voice` profile is not enabled, treat
that as a deployment contract failure rather than a valid degraded mode.

When Telegram smoke inputs are configured, the automated baseline may also run:

- `infra/scripts/smoke-telegram-ingress.py`

That check is intended for deterministic environments with stubbed downstream dependencies, such as CI or dedicated smoke stacks.
The CI smoke stack uses `ollama-fake` for model runtime calls and `telegram-fake` for Telegram delivery.

Telegram gating contract:

- deterministic Telegram smoke is part of the mandatory CI baseline
- the canonical deploy smoke runner executes Telegram smoke only when
  `TELEGRAM_SMOKE_*` inputs are explicitly configured for that environment
- the default production deploy path does not assume a stubbed Telegram backend
  and therefore does not require Telegram smoke by default
- manual production Telegram checks remain the higher-fidelity follow-up when
  deterministic smoke inputs are absent

Current CI baseline:

- `smoke-model` validates the text path and deterministic Telegram smoke
- `smoke-voice` is a mandatory `voice-enabled-cpu` gate with STT, TTS, and Open WebUI voice wiring checks

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

For the supported `voice-enabled-cpu` profile, readiness should already have
prewarmed the configured STT runtime before this smoke step begins.

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

### 11. Telegram ingress path works

Run this only if Telegram ingress is enabled in that environment.

For deterministic automated environments, use the stub-backed smoke runner.

Expected result:

- `telegram-ingress` health responds
- valid webhook update is accepted
- a second message in the same Telegram chat continues successfully through the same canonical backend conversation
- response flows through `telegram-ingress -> agent-api -> outbound send`
- invalid webhook secret is rejected
- retry-safe downstream failure behavior is preserved
- `/telegram/alerts` rejects invalid auth
- retryable `critical` alert delivery returns `accepted`, honors Telegram `429 retry_after`, then completes via durable retry without duplicate sends on replay when the same explicit idempotency key is reused
- `resolved` alert payloads are filtered by default unless explicitly enabled

## Pass/fail rule

A deployment passes smoke if:

- user chat works
- `agent-api` liveness and readiness are both correct
- storage is functional
- at least one tool path works if tools are enabled in that environment
- speech path works if speech is enabled in that environment
