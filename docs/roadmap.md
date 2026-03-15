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
- no milestone item may bypass the canonical request path

## Current state

- the repository contains working text, memory, tools, Telegram, and buffered
  voice slices
- Docker Compose topology exists for the accepted v1 core services
- `agent-api` exposes real OpenAI-compatible text and buffered voice endpoints
- `stt-service` and `tts-service` exist as real optional voice-profile
  services
- remaining work is primarily convergence and hardening rather than replacing
  placeholders

Current default-startup gap:

- the ordinary default startup is still text-first rather than voice-first
- Spotify support does not yet cover the intended user-facing playback and
  station surface
- Telegram does not yet expose a narrow outbound `telegram-send` and alias
  discovery baseline
- Telegram trusted-chat policy is now part of the documented baseline
  contract, but demo-household packaging and runtime implementation are still
  pending

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

This is the first real vertical slice for v1.

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
- the text path is observable and readiness-aware
- failure cases return explicit, stable API errors
- the text path is real, persisted, observable, and failure-stable

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

### Telegram channel extension status

Telegram ingress now exists as an implemented adjunct channel to the same canonical `agent-api` control plane, even though it is still outside the formal Milestone 2 exit criteria.

Current baseline:

- Telegram updates are normalized into `POST /v1/chat/completions` requests and responses are sent back to the originating chat
- per-chat conversation continuity is resolved in `agent-api` through backend-owned client session bindings
- webhook registration and long-polling fallback are both supported
- operational alert relay is available through a dedicated bot token and auth token
- alert delivery policy now supports severity-aware routing across default, warning, and critical recipient groups
- operational alert fanout now has durable retry/dedupe semantics via a Postgres-backed outbox
- no client-to-client tool bypass; Telegram-originated tool actions remain behind typed capabilities and are currently denied by policy
- request correlation and audit continuity are preserved across `telegram-ingress` and `agent-api`

Remaining hardening focus:

- build broader incident-management on top of the current durable retry/dedupe plus escalation alert fanout baseline
- expand command/approval behavior only when a concrete non-chat operational need justifies it

## Milestone 3: Voice and Hardening

### Goal

Only after Milestone 1 is stable, make voice a second-order v1 feature using the same orchestration core as text.

Current baseline:

- buffered STT and TTS services are already implemented behind the optional
  voice profile
- remaining work is centered on canonical persistence convergence, runtime
  policy, and operational hardening

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

## Milestone 4: Default Product Baseline

### Goal

Turn the ordinary default startup into a batteries-included baseline with voice
enabled and a narrow set of useful external actions.

### Scope

- make the supported CPU voice profile part of the default startup contract
- preserve one canonical orchestration path for text, voice, and tool use
- add user-facing Spotify playback, station, and playlist-discovery capabilities
- keep playlist CRUD as helper behavior rather than the primary user-facing
  contract
- add narrow trusted-chat Telegram send and alias-discovery capabilities
- keep Telegram bot commands minimal for household help and send flows
- preserve deny-by-default policy for ordinary Telegram free chat while adding
  a narrow allowlisted slash-command exception
- keep demo-to-real capability switching inside the same typed tool contract
- add smoke coverage for the default startup path instead of a specialty
  profile-only voice path

### Done when

- a default startup supports e2e voice interaction through `agent-api`
- the assistant can invoke baseline Spotify actions and alias-scoped Telegram
  send actions by voice
- users can discover available commands, aliases, playlists, and capability
  state without guessing provider internals
- the real Spotify path uses user-scoped OAuth rather than treating
  `client_credentials` as sufficient for state-changing operations
- playlist playback and station start are both supported through stable typed
  capabilities
- any playlist CRUD used for station-building remains an internal helper path
- recommendation-assisted playlist generation is optional rather than the only
  baseline mechanism
- Telegram bot commands and voice requests converge on the same typed tool
  boundary
- Telegram assistant access is limited to trusted household chats
- ordinary Telegram free chat remains deny-by-default for model-driven external
  effects
- Telegram bot commands remain limited to the minimal household helper surface

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
5. Default Product Baseline

## Change control

Any roadmap item that violates the architectural invariants requires an ADR update before implementation.
