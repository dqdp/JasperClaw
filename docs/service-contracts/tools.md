# Tools Integration Contract

## Purpose

This document defines the canonical v1 contract for the typed tools integration layer used by `agent-api`.

In v1, this is an **internal contract**, not a public HTTP API.

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

New tool IDs must be stable, explicit, and versioned by name rather than inferred from provider internals.

Each tool registration must also declare policy metadata such as risk class, confirmation requirements, allowed scopes, and audit fields.

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
