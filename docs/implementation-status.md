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
- a Docker Compose scaffold
- service placeholders for `agent-api`, `stt-service`, `tts-service`, and the legacy `tools-gateway` directory

The repository does **not** yet contain a real end-to-end assistant implementation.

## What is implemented today

### Repository and delivery scaffolding

Implemented:

- monorepo layout
- GitHub Actions CI
- image-build workflow
- deploy script scaffold
- smoke script scaffold
- Compose topology for the accepted v1 core services

### Documentation and architecture

Implemented:

- accepted ADR set through `ADR 0013`
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
- baseline conversation continuity via transcript-prefix matching and optional canonical conversation hints
- forward-only SQL migration runner for the current canonical text-path schema
- explicit `python -m app.cli migrate` command for applying pending schema changes before service traffic
- stubbed `POST /v1/audio/transcriptions`
- stubbed `POST /v1/audio/speech`

Not yet implemented:

- stronger client-to-backend conversation binding beyond transcript-prefix matching and optional hints
- retrieval-aware or memory-backed prompt assembly
- structured tracing beyond request ID and JSON event logs
- memory retrieval
- production-hardened runtime and storage observability

### `stt-service`

Implemented:

- service placeholder
- health endpoint

Not yet implemented:

- real transcription behavior
- production contract wiring

### `tts-service`

Implemented:

- service placeholder
- health endpoint

Not yet implemented:

- real speech synthesis behavior
- production contract wiring

### Tools integration

Implemented:

- accepted architectural decision that tools live in-process inside `agent-api` in v1
- in-process `web-search` and `spotify-*` policy-gated execution in `agent-api`
- canonical `tool_executions` persistence and basic tool planning audit

### Telegram ingress integration

Implemented:

- webhook ingestion service for Telegram updates
- idempotent update handling in the bridge layer
- `agent-api` fan-out path with conversation reuse by chat id
- startup webhook registration when `TELEGRAM_WEBHOOK_URL` is configured
- optional polling fallback when webhook URL is not configured
- operational alert relay via `/telegram/alerts` using a dedicated alert bot token

Not yet implemented:

- command intent routing before model execution (`/play`, `/status`, etc.)
- delivery policies and priority handling for operational alert fanout

### Database and memory

Implemented:

- accepted schema design and documentation
- forward-only SQL migrations for the current text-path tables
- readiness checks that fail when required migrations are still pending

Not yet implemented:

- full canonical schema beyond the current text-path subset
- retrieval behavior
- memory extraction

## Legacy scaffold note

The repository still contains `services/tools-gateway/` as a legacy placeholder directory.

Current accepted v1 meaning:

- it is not part of the active Compose topology
- it is not part of the active image-build matrix
- it does not define the accepted runtime architecture

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
