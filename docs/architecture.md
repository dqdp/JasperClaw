# Target Architecture v1

## Status

Proposed target architecture for repository bootstrap.

The accepted v1 implementation details are further refined by ADR 0004 through ADR 0013.

## Executive summary

The project uses the following principle:

> `agent-api` is the only canonical AI/backend ingress.

`Open WebUI` is treated as a UX shell and not as the assistant’s source of truth.

## v1 implementation priority

Implementation order matters in v1:

1. text path first
2. persistence, readiness, and failure-stable text behavior second
3. voice only after the text path is stable

## Architectural goals

The system should support a home/work assistant that can grow over time without rewriting its core control flow.

Primary goals:

- one canonical request path for text and voice
- one canonical place for memory, tool routing, and policy
- reproducible local and server runtime
- safe extension path for tools and integrations
- strong control over agent-side effects and execution scope
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
  -> Ollama / in-process tools adapters / stt-service / tts-service / Postgres
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

### 8. tools integration boundary

Responsibility:

- first-party typed adapters to external systems
- stable internal contracts for tools
- auth/token boundary for integrations
- capability-gated execution with explicit risk and approval metadata

v1 implementation rule:

- keep this boundary in-process inside `agent-api`
- treat it as an internal execution boundary, not a standalone service topology in v1
- extract a standalone `tools-gateway` later only if a real operational need appears

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

### `agent-api -> tools integration layer`

In v1, tool adapters remain in-process behind typed internal interfaces such as:

- `web-search`
- `spotify-search`
- `spotify-play`
- `spotify-pause`
- `spotify-next`

This is an internal contract boundary, not a required standalone service in v1.

If this layer is extracted later, the typed internal contract should remain stable.

## State ownership

### Open WebUI owns

- UI accounts and authentication
- UI chat and session presentation state
- UI-level preferences
- interface state

### `agent-api` owns

- canonical conversations and messages
- canonical assistant memory
- model run audit
- preferences relevant to assistant behavior
- tool credential references
- tool audit log
- document indexing state
- assistant profiles and policy state

UI history and canonical memory are intentionally separate concerns.

Use the following mental model consistently:

- transcript is the source interaction record
- execution audit is the source execution record
- derived memory is revisable projection state

## Suggested v1 data model

Minimum schema domains:

- `assistant_profiles`
- `principals`
- `conversations`
- `messages`
- `model_runs`
- `tool_executions`
- `memory_items`
- `retrieval_runs`
- `retrieval_hits`
- `tool_credentials`
- `document_sources`
- `document_chunks`

## Security posture

### Core rule

Secrets and privileged integrations must live behind `agent-api` and its internal integration boundaries, not in Open WebUI configuration as the canonical policy point.

Agent actions must remain capability-gated, least-privilege, and audit-first rather than relying on implicit model intent or broad execution access.

### Additional rules

- no public exposure of Ollama
- no public exposure of Postgres
- no public exposure of private tool adapters or any future extracted tool service
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

### Testing and linting

- use explicit lint gates in CI
- use layered verification across unit, integration, and smoke levels
- treat Linux + NVIDIA as the canonical runtime validation environment for model-backed behavior

### Delivery sequencing

- speech endpoints may exist before real voice implementation
- that does not make voice part of the first real delivery slice
- no implementation milestone may bypass the canonical request path

### Rollback

Rollback should primarily mean restoring the previously known-good image tag and re-running Compose.

### Readiness and error semantics

- `GET /healthz` is process liveness only
- `GET /readyz` means the core text path is ready
- optional tool or voice features must not fail global readiness unless explicitly required in that deployment mode
- request tracing and client-visible errors must follow a stable structured contract

## Invariants

1. All user-facing AI requests pass through `agent-api`.
2. Open WebUI is not the source of truth for memory, policy, or tool routing.
3. Production tools are not invoked directly from Open WebUI’s assistant models.
4. Ollama is an internal runtime, not a public assistant API.
5. Text and voice share one backend control path.
6. Agent actions are allowed only through explicit capabilities with bounded scope and audit.
7. The first real v1 slice is the text path, not voice.

## Deferred topics

These may be added later, but are intentionally deferred:

- MCP façade over the typed tools integration boundary
- richer memory management policies
- per-user isolated assistant principals
- job scheduler / reminders
- calendar and mail integration
- filesystem access policies
- multi-client auth propagation
- advanced observability stack
