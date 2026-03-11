# Roadmap

## Status

This roadmap tracks the transition from repository skeleton to a usable self-hosted assistant platform.

Accepted architecture refinements are captured in ADR 0004 through ADR 0013.

## Product goal

Deliver a self-hosted assistant where all user-facing AI traffic flows through `agent-api`, with one canonical orchestration path for text and voice.

## Architectural invariants

- `agent-api` is the only canonical AI/backend ingress
- `Open WebUI` is a UX shell, not the source of truth
- `Ollama` remains an internal runtime dependency
- canonical state lives in `Postgres + pgvector`
- tools are accessed only through the typed tools integration boundary owned by `agent-api`
- text and voice paths converge through `agent-api`

## Current state

- repository skeleton exists
- docker compose topology exists for the accepted v1 core services
- service stubs exist
- `agent-api` exposes placeholder OpenAI-compatible endpoints
- STT/TTS placeholders exist for the future voice path
- a legacy `services/tools-gateway/` placeholder directory still exists, but it is no longer part of the active v1 runtime topology

## Architecture review outcomes already accepted

- `Open WebUI` is a non-canonical UX projection layer
- canonical state is split across transcript, execution audit, and derived memory layers
- `agent-api` has one public OpenAI-compatible surface with layered internals
- tools stay in-process in v1 behind a typed integration boundary
- profile routing is explicit and has no automatic per-request fallback
- voice remains in v1 scope but only after the text path is stable
- auth is explicit at the `Open WebUI -> agent-api` ingress and network-private inside the runtime boundary
- readiness is defined around the core text path, with structured request tracing and stable client-visible error types
- agent actions are capability-gated, least-privilege, and audit-first
- linting and verification follow layered quality gates rather than ad hoc local checks

## Milestone 1: Control Plane MVP

### Goal

Replace the `agent-api` chat stub with a real orchestration path backed by `Ollama` and `Postgres`.

### Scope

- implement request and response schemas for OpenAI-compatible chat
- support non-streaming and SSE streaming chat completions
- map logical profiles `assistant-v1` and `assistant-fast` to internal models
- keep profile routing explicit and avoid automatic per-request fallback
- add `Ollama` client with timeout and error mapping
- add `Postgres` persistence for conversations, messages, requests, and model runs
- make `/readyz` depend on downstream readiness
- add integration tests for the text chat path

### Done when

- Open WebUI can chat through `agent-api`
- responses come from a real model, not a stub
- chat history and request metadata are persisted
- failure cases return explicit, stable API errors

## Milestone 2: Memory and Tools

### Goal

Add durable assistant memory and typed tool execution without bypassing the control plane.

### Scope

- design `pgvector` schema for memory and retrieval
- add embedding generation and storage
- add retrieval during prompt assembly
- implement a typed tools integration boundary inside `agent-api`
- add first tools: `web-search`, `spotify-search`, `spotify-play`, `spotify-pause`, `spotify-next`
- add tool policy, timeout, and audit logging
- add integration tests for memory retrieval and tool calls

### Done when

- the assistant can use persisted context across sessions
- tools are invoked only through the typed integration boundary owned by `agent-api`
- tool executions are auditable
- retrieval materially influences responses

## Milestone 3: Voice and Hardening

### Goal

After the text path is stable, make voice a first-class path using the same orchestration core as text.

### Scope

- implement real `stt-service` and `tts-service`
- normalize voice requests through `agent-api`
- persist voice interactions in the same canonical model
- add structured logs and request tracing
- complete smoke tests, backup and rollback checks, and deploy hardening

### Done when

- voice requests use the same memory and tool policies as text
- deployment and rollback are repeatable
- key operational failure modes are observable

## Deferred for v2

- autonomous background agents
- complex workflow automation
- multi-user tenant model
- Kubernetes
- event bus and distributed orchestration

## Delivery order

1. Architecture review and ADR capture
2. Control Plane MVP
3. Memory and Tools
4. Voice and Hardening

## Change control

Any roadmap item that violates the architectural invariants requires an ADR update before implementation.
