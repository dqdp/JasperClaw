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
- stubbed `POST /v1/chat/completions`
- stubbed `POST /v1/audio/transcriptions`
- stubbed `POST /v1/audio/speech`

Not yet implemented:

- real `Ollama` orchestration
- canonical persistence in `Postgres`
- structured request tracing
- real readiness logic
- memory retrieval
- tool execution
- stable error mapping beyond placeholders

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

Not yet implemented:

- actual in-process tool adapter layer
- web search adapter
- Spotify adapters
- tool policy and audit persistence

### Database and memory

Implemented:

- accepted schema design and documentation

Not yet implemented:

- migrations
- canonical tables
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
- canonical transcript persistence
- execution audit in `Postgres`
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
