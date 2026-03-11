# Target Architecture v1

## Status

Proposed target architecture for repository bootstrap.

## Executive summary

The project uses the following principle:

> `agent-api` is the only canonical AI/backend ingress.

`Open WebUI` is treated as a UX shell and not as the assistant’s source of truth.

## Architectural goals

The system should support a home/work assistant that can grow over time without rewriting its core control flow.

Primary goals:

- one canonical request path for text and voice
- one canonical place for memory, tool routing, and policy
- reproducible local and server runtime
- safe extension path for tools and integrations
- operational simplicity for a single host setup
- clear future path to richer automation and more clients

## Non-goals for v1

- distributed orchestration
- autonomous background agents
- multi-tenant enterprise architecture
- Kubernetes-based platform
- complex event-driven topology

## Canonical request path

```text
User
  -> Caddy
  -> Open WebUI
  -> agent-api
  -> Ollama / tools-gateway / stt-service / tts-service / Postgres
```

This path must remain true for:

- text chat
- voice chat
- future mobile/PWA usage
- future alternative clients (CLI, shortcuts, lightweight apps)

## Component model

### 1. Caddy

Responsibility:

- public ingress
- TLS termination
- reverse proxying
- WebSocket support

Design intent:

- expose only ports 80/443 externally
- keep internal services private to Docker networks

### 2. Open WebUI

Responsibility:

- user-facing UI
- authentication for UI users
- session/chat UX
- file upload UX
- voice UI
- mobile/PWA experience
- admin/operator interface

Must not own:

- canonical assistant memory
- tool credentials
- routing policy
- model routing policy
- direct production tool execution path

Design rule:

Open WebUI must know only one backend: `agent-api`.

### 3. agent-api

Responsibility:

- canonical OpenAI-compatible façade
- orchestration of assistant requests
- prompt policy application
- profile/model routing
- memory lookup and updates
- tool planning and execution policy
- audit and operational logging
- speech request normalization

This is the most important service in the system.

### 4. Ollama

Responsibility:

- chat inference
- embeddings

Must remain an internal runtime component.

It should not be exposed as the user-facing API in production.

### 5. Postgres + pgvector

Responsibility:

- canonical assistant state
- memory items
- memory embeddings
- conversation projections
- document chunks and retrieval state
- tool audit trail
- preferences and profile state

### 6. stt-service

Responsibility:

- speech-to-text via a thin HTTP wrapper over faster-whisper

### 7. tts-service

Responsibility:

- text-to-speech via a thin HTTP wrapper over Piper

### 8. tools-gateway

Responsibility:

- first-party typed adapters to external systems
- stable internal contracts for tools
- auth/token boundary for integrations

Expected initial tool surface:

- web search
- Spotify search
- Spotify play
- Spotify pause
- Spotify next

## Why `agent-api` is the center

### Advantages

- no split-brain between UI and backend logic
- one source of truth for policies and memory
- same behavior across text and voice
- easier testing and observability
- easier future addition of alternative clients
- safer handling of secrets and tool policies

### Trade-off

- more backend work up front
- fewer shortcut features from UI-first tooling
- need to explicitly define internal contracts early

This trade-off is accepted because the project goal is a long-lived assistant platform, not just a demo chat UI.

## Network boundaries

Three Docker networks are recommended.

### `frontend`

Contains:

- caddy
- open-webui

Purpose:

- public ingress and user-facing traffic

### `control`

Contains:

- open-webui
- agent-api

Purpose:

- single UI-to-backend control path

### `runtime`

Contains:

- agent-api
- ollama
- postgres
- stt-service
- tts-service
- tools-gateway

Purpose:

- private backend execution network

### Boundary rule

`open-webui` must not join `runtime`.

That rule prevents accidental direct access to Ollama or internal tools.

## Runtime shape

### Native host software

Only these components should remain native on Ubuntu 24.04:

- NVIDIA driver
- Docker Engine
- Docker Compose plugin
- Docker Buildx plugin
- NVIDIA Container Toolkit

### Containerized application components

Everything else should run in containers.

This includes:

- Caddy
- Open WebUI
- agent-api
- Ollama
- Postgres
- stt-service
- tts-service
- tools-gateway

## API surface design

## Public API exposed by `agent-api`

The public surface is OpenAI-compatible and intended for Open WebUI.

Minimum endpoints:

- `GET /v1/models`
- `POST /v1/chat/completions`
- `POST /v1/audio/transcriptions`
- `POST /v1/audio/speech`
- optional `POST /v1/embeddings`

### Model exposure rule

The API should expose **logical assistant profiles**, not raw runtime model IDs.

Examples:

- `assistant-v1`
- `assistant-fast`
- `embed-v1`

This avoids coupling UI behavior to Ollama internals.

## Internal service contracts

### `agent-api -> ollama`

Use Ollama native API for:

- chat
- embeddings

### `agent-api -> stt-service`

Simple HTTP endpoint:

- `POST /transcribe`

### `agent-api -> tts-service`

Simple HTTP endpoint:

- `POST /speak`

### `agent-api -> tools-gateway`

Typed HTTP endpoints such as:

- `POST /tools/web-search`
- `POST /tools/spotify/search`
- `POST /tools/spotify/play`
- `POST /tools/spotify/pause`
- `POST /tools/spotify/next`

For v1, use ordinary internal HTTP/OpenAPI contracts rather than MCP as the primary internal protocol.

## State ownership

### Open WebUI owns

- UI accounts and authentication
- UI chat history
- UI-level preferences
- interface state

### `agent-api` owns

- canonical assistant memory
- preferences relevant to assistant behavior
- tool credential references
- tool audit log
- document indexing state
- assistant profiles and policy state

UI history and canonical memory are intentionally separate concerns.

## Suggested v1 data model

Minimum schema domains:

- `assistant_profiles`
- `principals`
- `conversations`
- `messages`
- `memory_items`
- `memory_embeddings`
- `tool_credentials`
- `tool_audit_log`
- `document_sources`
- `document_chunks`

## Security posture

### Core rule

Secrets and privileged integrations must live behind `agent-api` and/or `tools-gateway`, not in Open WebUI configuration as the canonical policy point.

### Additional rules

- no public exposure of Ollama
- no public exposure of Postgres
- no public exposure of tools-gateway
- no direct production tool execution from Open WebUI assistant models
- treat terminal access as an operator-only concern, not general assistant capability

## Operational stance

### Versioning

Production must prefer pinned image tags over floating tags.

### Deployment

- build in GitHub Actions
- push images to GHCR
- deploy to host over SSH
- use manual approval on production environment

### Rollback

Rollback should primarily mean restoring the previously known-good image tag and re-running Compose.

## Invariants

1. All user-facing AI requests pass through `agent-api`.
2. Open WebUI is not the source of truth for memory, policy, or tool routing.
3. Production tools are not invoked directly from Open WebUI’s assistant models.
4. Ollama is an internal runtime, not a public assistant API.
5. Text and voice share one backend control path.

## Deferred topics

These may be added later, but are intentionally deferred:

- MCP façade over tools-gateway
- richer memory management policies
- per-user isolated assistant principals
- job scheduler / reminders
- calendar and mail integration
- filesystem access policies
- multi-client auth propagation
- advanced observability stack
