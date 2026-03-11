# Error Semantics

## Purpose

Define the stable public error behavior for `local-assistant` and the rules for mapping internal failures into client-visible responses.

## Core rule

Client-facing errors must be:

- machine-readable
- stable at the type level
- specific enough to automate against
- sanitized so raw dependency failures do not leak directly to clients

## Error envelope

Public APIs should use this shape:

```json
{
  "error": {
    "type": "dependency_unavailable",
    "code": "runtime_unavailable",
    "message": "Model runtime unavailable",
    "request_id": "req_123"
  }
}
```

## Error types

Stable top-level types:

- `validation_error`
- `authentication_error`
- `authorization_error`
- `policy_error`
- `rate_limit_error`
- `dependency_unavailable`
- `upstream_error`
- `internal_error`

## Suggested HTTP mapping

- `validation_error` -> `400` or `422`
- `authentication_error` -> `401`
- `authorization_error` -> `403`
- `policy_error` -> `403`
- `rate_limit_error` -> `429`
- `dependency_unavailable` -> `503` or `504`
- `upstream_error` -> `502`
- `internal_error` -> `500`

## Stable code examples

Validation and request codes:

- `invalid_request`
- `missing_required_field`
- `unknown_profile`
- `unsupported_feature`

Authentication and authorization codes:

- `invalid_client_credentials`
- `forbidden_client`

Policy codes:

- `tool_not_allowed`
- `voice_not_enabled`

Dependency codes:

- `database_unavailable`
- `runtime_unavailable`
- `dependency_timeout`
- `speech_service_unavailable`

Upstream response codes:

- `dependency_bad_response`
- `dependency_protocol_error`

Internal codes:

- `internal_failure`
- `unexpected_state`

## Mapping rules

- raw provider messages must not be passed through verbatim to clients
- specific dependency names may appear in `code`, but internal stack traces must remain in logs only
- dependency timeouts should be explicit rather than folded into generic `internal_error`
- unknown profiles should fail as `validation_error`, not as runtime failures
- denied tool use should fail as `policy_error`, not as `dependency_unavailable`

## Streaming rule

If a streaming request fails before the first chunk, return the normal error envelope.

If it fails after streaming has started:

- log the failure with the same `request_id`
- include dependency and error classification in logs
- terminate the stream cleanly if possible

## Logging rule

Every failed request log must include:

- `request_id`
- `error_type`
- `error_code`
- `route`
- `dependency` when relevant
- `outcome`

## Operational use

The main value of the error taxonomy is not only API cleanliness.

It also drives:

- smoke test expectations
- alert routing
- rollback decisions
- future dashboards and metrics labels
