# Chat Flow

## Purpose

Define the canonical v1 text-chat flow from `Open WebUI` to `agent-api`, persistence, and the final response.

This document is the execution-level companion to:

- `ADR 0004` for UI state ownership
- `ADR 0005` for the canonical data model
- `ADR 0006` for `agent-api` layering
- `ADR 0008` for profile routing
- `ADR 0011` for readiness, observability, and error semantics

## Scope

This document covers the primary text path:

`Open WebUI -> agent-api -> Postgres/Ollama -> agent-api -> Open WebUI`

It assumes:

- `Open WebUI` is the UX shell
- `agent-api` is the only canonical backend ingress
- `Ollama` is the primary runtime
- `Postgres` is the canonical store

It does not fully specify:

- the future voice path
- document ingestion
- advanced tool-calling orchestration beyond the hook points where tools may later appear

## Core invariants

- all user-facing AI text requests enter through `agent-api`
- `Open WebUI` message history is input context, not canonical ownership
- canonical transcript and execution audit are written behind `agent-api`
- public profile selection uses logical profile IDs such as `assistant-v1`
- no automatic per-request runtime fallback is performed

## High-level sequence

```text
User
  -> Open WebUI
  -> agent-api /v1/chat/completions
  -> request validation + request_id
  -> profile resolution
  -> conversation resolution
  -> optional memory retrieval
  -> Ollama model run
  -> canonical persistence
  -> OpenAI-compatible response
  -> Open WebUI
```

## Canonical request flow

### 1. UI submission

The user submits a text prompt through `Open WebUI`.

`Open WebUI` sends an OpenAI-compatible `POST /v1/chat/completions` request to `agent-api` using the internal shared credential.

The request includes:

- selected logical profile, for example `assistant-v1`
- current message history in OpenAI-compatible form
- whether the response should stream
- `Authorization: Bearer <INTERNAL_OPENAI_API_KEY>`

### 2. Ingress and request correlation

At ingress, `agent-api` must:

- authenticate the trusted client
- assign or propagate a request ID
- log `request_received`
- validate the transport payload

Current v1 baseline:

- all `/v1/*` text requests require the shared internal bearer credential
- placeholder bearer values such as `change-me` are treated as not configured
- `healthz` and `readyz` are intentionally left unauthenticated because they are operational probes, not user traffic

If validation fails, return a stable machine-readable error without invoking downstream dependencies.

### 3. Profile resolution

`agent-api` resolves the public profile ID to an internal runtime configuration.

This step must:

- reject unknown profiles as `validation_error`
- resolve the chosen profile to one explicit `Ollama` runtime target
- avoid hidden runtime fallback

The selected profile and resolved runtime target must become part of request context and audit state.

### 4. Conversation resolution

`agent-api` resolves the canonical backend conversation context.

Rules:

- `Open WebUI` chat identifiers are treated as client metadata
- canonical `conversations.id` is owned by the backend
- the backend may create or continue a canonical conversation based on request metadata and policy

Current v1 baseline:

- `agent-api` accepts an explicit canonical hint via `X-Conversation-ID`
- `agent-api` also accepts `metadata.conversation_id` when the client can send it
- if no hint is available, `agent-api` continues the best matching conversation whose persisted non-empty transcript is a prefix of the incoming message list
- if no matching conversation exists, `agent-api` creates a new canonical conversation

The result of this step is one canonical `conversation_id` used for persistence and tracing.

### 5. Transcript normalization

The incoming OpenAI-style messages are normalized into the canonical transcript model.

The canonical representation should preserve:

- message role
- human-readable content
- message ordering
- client linkage metadata where available

The backend must not treat the raw UI payload as the canonical stored format.

### 6. Optional memory retrieval

If memory retrieval is enabled for the selected profile and deployment stage, `agent-api` performs retrieval before the model call.

This step may:

- create a `retrieval_run`
- select matching `memory_items`
- record `retrieval_hits`
- assemble additional context for the model prompt

If retrieval is not enabled yet, the text path still proceeds without it.

### 7. Model-run initialization

Before invoking `Ollama`, `agent-api` creates a `model_runs` record or otherwise reserves audit state for the attempt.

At minimum the model-run audit should capture:

- `request_id`
- `conversation_id`
- public `profile_id`
- internal runtime provider and model
- start time
- initial status

### 8. Runtime invocation

`agent-api` invokes `Ollama` through the runtime client.

This step must:

- use the resolved runtime configuration
- propagate request correlation
- classify timeout, availability, and bad-response failures using the stable error taxonomy

If the runtime is unavailable, the request fails explicitly. It must not silently fall back to a different model.

### 9. Assistant response materialization

On success, `agent-api` materializes the assistant output into the canonical transcript model.

At minimum this should include:

- one assistant `messages` record
- final `model_runs` status
- latency and token metadata when available
- conversation timestamp updates

If later tool execution becomes part of the text path, tool activity must be recorded separately in `tool_executions` rather than embedded only in free-form logs.

### 10. Response adaptation

`agent-api` converts the internal result back into an OpenAI-compatible response for `Open WebUI`.

#### Non-streaming mode

Return one complete OpenAI-compatible completion payload.

The canonical backend conversation identifier is returned in the `X-Conversation-ID` response header.

#### Streaming mode

Return SSE chunks in stable order.

Current v1 baseline:

- `agent-api` consumes the chunked `Ollama` chat stream directly
- `agent-api` forwards assistant content incrementally as OpenAI-style SSE chunks
- the final runtime chunk is used to finalize usage metadata and persistence

Rules:

- if failure occurs before the first chunk, return the normal error envelope
- if failure occurs after streaming starts, log it with the same `request_id`, terminate the stream, and do not emit a synthetic `data: [DONE]`
- persistence and model-run finalization must still be completed or explicitly failed
- the `X-Conversation-ID` response header still carries the canonical conversation identifier

## Persistence model touched by the text flow

Required tables for the first working path:

- `assistant_profiles`
- `principals`
- `conversations`
- `messages`
- `model_runs`

Optional but adjacent tables:

- `tool_executions`
- `memory_items`
- `retrieval_runs`
- `retrieval_hits`

## Observability requirements

Every text request must emit enough structured information to reconstruct the flow.

Minimum events:

- `request_received`
- `request_validated`
- `profile_resolved`
- `conversation_resolved`
- `retrieval_started` and `retrieval_completed` when retrieval is enabled
- `model_run_started`
- `dependency_call_completed`
- `persistence_write_completed`
- `request_completed` or `request_failed`

Minimum shared fields:

- `request_id`
- `conversation_id` when resolved
- `profile_id`
- `route`
- `outcome`

## Failure behavior

### Validation failure

- fail before downstream calls
- no model invocation
- return `validation_error`

### Authentication failure

- fail before business logic
- return `authentication_error`

### Runtime unavailable

- fail after profile resolution, before successful response generation
- record failed `model_runs` audit state if initialization already happened
- return `dependency_unavailable` or `upstream_error` according to the mapped failure class

### Persistence failure

- if persistence fails before responding, fail the request explicitly
- if persistence fails after streaming begins, log the failure with request correlation and mark the run as failed or partial according to implementation policy

## v1 implementation order

To make this flow real in code, the first text-path delivery should proceed in this order:

1. validate and normalize the OpenAI-compatible request
2. resolve the selected profile
3. resolve or create the canonical conversation
4. initialize and persist model-run audit state
5. invoke `Ollama`
6. persist the assistant response
7. return the OpenAI-compatible result
8. add retrieval and tool steps only after the base path is stable

## Explicitly deferred

- full tool-planning behavior inside the text flow
- document retrieval insertion into the prompt
- voice-triggered transcript continuation
- cross-client conversation merge semantics
