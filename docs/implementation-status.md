# Implementation Status

## Purpose

State clearly what is already implemented, what is still a placeholder, and what exists only as accepted design.

This document is intentionally blunt.

It should be read alongside:

- `docs/architecture.md`
- `docs/roadmap.md`
- `docs/backlog.md`

## Current status summary

The repository currently contains:

- an accepted architecture and ADR set
- a working documentation baseline for data model, chat flow, configuration, observability, and error semantics
- a Docker Compose runtime topology
- real `agent-api`, `stt-service`, `tts-service`, and `telegram-ingress`
  service implementations
- the legacy `tools-gateway` placeholder directory, which is not part of the
  canonical runtime path

The repository does **not** yet contain a fully hardened production platform.

## What is implemented today

### Repository and delivery scaffolding

Implemented:

- monorepo layout
- layered GitHub Actions CI with mandatory text, voice, and deterministic Telegram smoke coverage
- image-build workflow
- deploy script with explicit rollout profile contract checks and canonical smoke gating
- canonical smoke flow covering `text-only` and `voice-enabled-cpu` profiles
- automated Open WebUI voice wiring validation in the canonical voice smoke flow
- reproducible backup/restore drill helper for disposable Postgres validation
- reproducible rollback drill helper for deterministic immutable-tag validation
- shared step/timing logs across deploy and release-drill scripts
- Compose topology for the accepted v1 core services

### Documentation and architecture

Implemented:

- accepted ADR set through `ADR 0016`
- roadmap and backlog
- canonical `agent-api` service contract
- canonical tools integration contract
- canonical data model spec
- canonical text chat flow
- ops docs for configuration, observability, error semantics, and agent action policy

### `agent-api`

Implemented:

- FastAPI app bootstrapping
- `GET /healthz`
- `GET /readyz`
- `GET /v1/models`
- shared internal bearer authentication enforced on `/v1/*`, with `healthz` and `readyz` left open
- real profile-based `POST /v1/chat/completions` for `stream=false`
- real token streaming path for `stream=true`, bridging `Ollama` chat chunks into OpenAI-style SSE
- real `Ollama` chat runtime call for text requests
- stable error envelopes for request validation and runtime/storage failures
- request ID attachment via `X-Request-ID`
- structured request logging for request lifecycle, readiness, runtime, and storage outcomes
- request-scoped persistence for `conversations`, `messages`, `model_runs`, and baseline `tool_executions`
- baseline conversation continuity via explicit canonical hints, backend-owned client session bindings, and transcript-prefix fallback
- optional retrieval-aware prompt assembly with conservative memory materialization from `user` transcript turns
- retrieval and memory audit persistence through `memory_items`, `retrieval_runs`, and `retrieval_hits`
- forward-only SQL migration runner for the current canonical text-path schema
- explicit neutral `platform-db` migration command for applying pending schema changes before service traffic
- buffered `POST /v1/audio/transcriptions` proxy path through `stt-service`
- buffered `POST /v1/audio/speech` proxy path through `tts-service`

Not yet implemented:

- structured tracing beyond request ID and JSON event logs
- richer memory retention, invalidation, and deletion flows
- production-hardened runtime and storage observability

### `stt-service`

Implemented:

- buffered `POST /transcribe` transcription endpoint
- `GET /healthz`, `GET /readyz`, and `GET /metrics`
- bounded-concurrency transcription facade
- `faster-whisper` engine boundary with lazy runtime initialization
- readiness that preloads the active STT runtime before serving traffic
- structured request logging and first-wave transcription/readiness metrics

Not yet implemented:

- premium GPU-backed STT profile

### `tts-service`

Implemented:

- buffered `POST /speak` synthesis endpoint
- `GET /healthz` and `GET /readyz`
- `GET /metrics` with request, synthesis, and readiness metrics
- static voice registry and bounded-concurrency synthesis facade
- Piper-compatible first local backend path
- Docker packaging that installs the Piper runtime and preloads the bundled default voice models
- manual Docker smoke coverage for `agent-api -> tts-service -> Piper-compatible backend`
- mandatory CI and deploy-time automated voice smoke coverage through `agent-api` for the supported `voice-enabled-cpu` profile
- automated Open WebUI voice wiring validation in the canonical voice smoke flow

Not yet implemented:

- premium XTTS GPU profile
- streaming synthesis

### Tools integration

Implemented:

- accepted architectural decision that tools live in-process inside `agent-api` in v1
- accepted architectural decision that any future `tools-gateway` extraction must preserve `agent-api` as the canonical control plane
- in-process `web-search` and `spotify-*` policy-gated execution in `agent-api`
- bounded one-hop model-driven tool planning with fail-open fallback into the final answer path
- canonical `tool_executions` persistence and basic tool planning audit
- Telegram-originated tool actions are denied by policy inside `agent-api`

### Telegram ingress integration

Implemented:

- webhook ingestion service for Telegram updates
- idempotent update handling in the bridge layer
- `agent-api` fan-out path with backend-owned conversation continuity for Telegram chats
- startup webhook registration when `TELEGRAM_WEBHOOK_URL` is configured
- optional polling fallback when webhook URL is not configured
- operational alert relay via `/telegram/alerts` using a dedicated alert bot token
- severity-aware alert routing via default/warning/critical Telegram recipient groups
- durable alert outbox with retry/dedupe semantics for operational Telegram fanout
- minimal command routing for `/help`, `/status`, and `/ask`
- slash-command allowlist and request ID continuity across ingress handling
- Telegram-originated tool actions are tagged at ingress and denied inside `agent-api`
- deterministic CI smoke coverage for ingress, continuity, negative auth paths, and durable alert-delivery behavior

Not yet implemented:

- richer command/approval routing beyond the current local command set
- broader incident-management beyond the current bounded retry/dedupe plus escalation alert fanout baseline

### Database and memory

Implemented:

- accepted schema design and documentation
- forward-only SQL migrations for the current text-path and memory-foundation tables
- readiness checks that fail when required migrations are still pending
- conservative memory extraction/materialization from selected `user` turns with
  explicit durable-signal phrases
- retrieval query behavior with explicit audit traces
- fixed retrieval fixtures for positive, false-positive, and stale-memory cases
- explicit `active -> invalidated -> deleted` lifecycle transitions for memory items
- candidate-decision and skip-reason observability for the memory path
- operator-facing memory inspection runbook

Not yet implemented:

- full canonical schema beyond the current text-path subset
- automatic retention/expiry behavior and richer invalidation heuristics
- broader memory extraction strategies beyond the current conservative baseline

## Legacy scaffold note

The repository still contains `services/tools-gateway/` as a legacy placeholder directory.

Current accepted v1 meaning:

- it is not part of the active Compose topology
- it is not part of the active image-build matrix
- it does not define the accepted runtime architecture
- it is only future extraction scaffold unless a later ADR explicitly activates a standalone tools runtime

It remains only as leftover scaffold material unless a later extraction is deliberately reintroduced.

## What is canonical but not yet real

These are accepted target behaviors, not current runtime facts:

- `agent-api` as the real orchestration layer
- transcript as the source interaction record
- execution audit in `Postgres` as the source execution record
- derived memory as revisable projection state
- profile-based runtime routing
- in-process tools integration
- voice after text-path stabilization
- structured observability and stable error semantics

## Immediate implication for contributors

Do not confuse:

- documented target behavior

with:

- implemented service behavior

When changing code, use the ADR set and canonical docs as the design baseline, but verify the current code before assuming the feature already exists.
