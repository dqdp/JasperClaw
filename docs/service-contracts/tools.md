# Tools Integration Contract

## Purpose

This document defines the canonical v1 contract for the typed tools integration layer used by `agent-api`.

In v1, this is an **internal contract**, not a public HTTP API.
It defines an internal execution boundary, not a standalone service topology.

Risk classification, approval requirements, and sandbox expectations for tools are governed by `docs/ops/agent-action-policy.md`.

## Responsibilities

`agent-api` owns:

- tool selection and policy decisions
- request correlation and audit ownership
- orchestration around model execution and tool execution

The tools integration layer owns:

- typed tool request and response envelopes
- provider-specific adapters
- timeout, retry, and provider error mapping behavior

## Non-responsibilities

- direct public tool endpoints
- arbitrary user-supplied command execution
- long-running background jobs in v1
- bypassing `agent-api` policy or audit

## v1 tool IDs

The initial v1 tool catalog is intentionally small:

- `web-search`
- `spotify-search`
- `spotify-play`
- `spotify-pause`
- `spotify-next`

Current Tools Slice 2 baseline:

- `web-search` and Spotify playback/search actions are executable in this slice
- all declared tool IDs exist in policy catalog
- tool use remains internal to `agent-api` and is not exposed as a public HTTP API
- `web-search` may run either through explicit `metadata.web_search=true` or through one bounded internal planning pass inside `POST /v1/chat/completions`
- the model-driven path is capped at one tool hop per request
- tool failures are fail-open relative to the core text response path, but must still be logged and audited
- unsupported or not-yet-implemented tool requests are denied by policy and surfaced to the final model path with a policy failure note when fallback is enabled

New tool IDs must be stable, explicit, and versioned by name rather than inferred from provider internals.

Each tool registration must also declare policy metadata such as risk class, confirmation requirements, allowed scopes, and audit fields.

## Current Telegram integration baseline

Telegram is an implemented external ingress channel, not a replacement for the canonical client contract.

Current baseline:

- Telegram-to-chat bridge normalizes incoming Telegram messages into `POST /v1/chat/completions` requests
- no public Telegram tool endpoint exists; all tool execution remains inside `agent-api` policy gates
- Telegram forwards `metadata.source=telegram` plus a stable `metadata.client_conversation_id` derived from `chat_id`; `agent-api` resolves that binding to a canonical backend conversation
- Telegram-originated requests carry source metadata so tool policy can deny external-effect actions from this ingress
- request correlation is preserved across ingress, orchestration, and tool-audit paths
- operational alert delivery uses a dedicated alert bot plus auth token, with severity-aware routing for default/warning/critical recipient groups

Safety note:

- Telegram is treated as untrusted inbound traffic until normalized and converted into canonical `POST /v1/chat/completions` requests.
- all Telegram-driven action paths must pass the same typed tool policy as native clients before execution.
- every side-effect-capable action from Telegram requires explicit allow rules, approval flow if applicable, and immutable audit context (`request_id`, `conversation_id`, `model_run_id`).

Remaining hardening:

- persistent alert retries/dedupe/escalation remain follow-up work beyond the current routing policy baseline

## Safe Telegram integration requirements

Telegram integration is explicitly sensitive because it touches external user messaging channels and credentials.

- treat all Telegram-originated external effects as at least `R3` in `docs/ops/agent-action-policy.md`
- avoid raw provider calls from model output or unvalidated handlers
- require typed tool envelopes for any action that can mutate external state
- enforce explicit allow/deny policy and confirmation requirements through the same policy layer as other tools
- keep Telegram credentials scoped, never persisted into prompt context, and rotated according to deployment policy
- enforce webhook verification, idempotency by Telegram message identity, and strict rate limits
- persist audit rows with `request_id`, `conversation_id`, and `model_run_id` for every side-effect path

## Canonical request envelope

Every tool execution is normalized into one typed internal request shape.

Required fields:

- `tool`
- `invocation_id`
- `arguments`

Recommended fields:

- `request_id`
- `conversation_id`
- `model_run_id`
- `timeout_ms`

Example:

```json
{
  "tool": "web-search",
  "invocation_id": "tool_123",
  "request_id": "req_123",
  "conversation_id": "conv_123",
  "model_run_id": "run_123",
  "timeout_ms": 5000,
  "arguments": {
    "query": "OpenAI API changelog"
  }
}
```

## Canonical response envelope

Every tool adapter returns one normalized result shape.

Required fields:

- `tool`
- `invocation_id`
- `status`
- `latency_ms`

Success example:

```json
{
  "tool": "web-search",
  "invocation_id": "tool_123",
  "status": "ok",
  "provider": "search-provider",
  "latency_ms": 412,
  "output": {
    "results": []
  }
}
```

Failure example:

```json
{
  "tool": "web-search",
  "invocation_id": "tool_123",
  "status": "error",
  "provider": "search-provider",
  "latency_ms": 412,
  "error": {
    "type": "upstream_error",
    "code": "provider_unavailable",
    "message": "Search provider unavailable"
  }
}
```

## Execution rules

- All tool execution starts inside `agent-api`; clients do not call tools directly.
- Each execution must have a unique `invocation_id`.
- Tool arguments must be typed and validated per tool; raw free-form provider payloads are not the contract.
- Each registered tool must declare capability metadata including `risk_class`, `requires_confirmation`, `sandbox_profile`, and `allowed_scopes`.
- Every tool execution must have a bounded timeout.
- Automatic retries are allowed only for safe read-like tools such as `web-search` and `spotify-search`.
- Automatic retries are not allowed by default for state-changing tools such as `spotify-play`, `spotify-pause`, and `spotify-next`.
- Tool responses must be normalized before they are exposed to orchestration or persistence.

Current `web-search` adapter baseline:

- provider contract: `GET {SEARCH_BASE_URL}/search?q=<query>&limit=<k>`
- bearer authentication uses `SEARCH_API_KEY`
- normalized result items contain `title`, `url`, and `snippet`
- in the model-driven path, the planner may request only `{"tool":"web-search","query":"..."}` as a strict JSON directive

## Error contract

Tool-layer failures must map into the same stable error taxonomy used by `agent-api`.

Allowed top-level error types:

- `validation_error`
- `policy_error`
- `dependency_unavailable`
- `upstream_error`
- `internal_error`

Provider-specific errors must not leak through as the canonical contract.

## Audit contract

Every execution must be auditable through canonical persistence.

Minimum audit fields:

- `invocation_id`
- `tool`
- `request_id` when present
- `conversation_id` when present
- `model_run_id` when present
- normalized arguments
- outcome `status`
- `provider`
- `latency_ms`
- stable error `type` and `code` when failed

## Extraction compatibility

The internal request and response envelopes should remain stable enough that the tools integration layer can later be extracted into a standalone service if a real operational need appears.

That extraction path is a future deployment change, not a v1 contract change.

Do not introduce a standalone tools service in v1 unless an ADR explicitly reopens that decision.
