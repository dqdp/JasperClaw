# Observability

## Purpose

Define the minimum operational signals required to run `local-assistant` without guessing about service health, request flow, or failure cause.

## Goals

- know whether the core text path can serve traffic
- trace one request across orchestration steps
- distinguish core-path outages from optional-feature outages
- support smoke, rollback, and production debugging

## Core principle

Observability in v1 is centered on the canonical text path:

`Open WebUI -> agent-api -> Ollama/Postgres`

Optional features such as voice and some tool adapters should add signals, but they must not blur the core-path contract.

## Request correlation

Every request must have a request identifier.

Rules:

- accept an incoming request ID if a trusted upstream already provides one
- otherwise generate one at ingress
- return the same ID in the response header when possible
- include the same ID in all structured logs for that request

Recommended header:

- `X-Request-ID`

## Structured logs

Logs should be structured JSON or another machine-parseable format.

Minimum fields:

- `timestamp`
- `level`
- `service`
- `event`
- `request_id`
- `route`
- `outcome`

Context-specific fields:

- `profile_id`
- `conversation_id`
- `dependency`
- `latency_ms`
- `status_code`
- `error_type`
- `error_code`

## Required log events

At minimum:

- `request_received`
- `request_validated`
- `dependency_call_started`
- `dependency_call_completed`
- `persistence_write_completed`
- `request_completed`
- `request_failed`
- `readiness_check_completed`

## Health and readiness semantics

### `agent-api`

`GET /healthz`

- answers whether the process is alive
- must not fail only because a downstream dependency is down

`GET /readyz`

- answers whether the core text path is ready
- must fail if config is invalid
- must fail if `Postgres` is unavailable
- must fail if the primary chat runtime is unavailable
- must not fail only because optional tool adapters are unavailable
- must not fail only because voice dependencies are unavailable unless voice is explicitly enabled as a required runtime feature

### `Open WebUI`

- health is practical reachability of the UI and login path
- backend-specific readiness belongs to `agent-api`, not to the UI shell

### `Ollama`

- operationally relevant when it can answer the model runtime calls required by the active profiles

### `Postgres`

- operationally relevant when it accepts connections and the required schema is usable

### `stt-service` and `tts-service`

- required for voice-only features
- should be checked independently when voice is enabled
- should not fail the global core-text readiness contract by default

## Metrics and counters

If metrics are added in v1, start with:

- request count by route and outcome
- request latency by route
- dependency latency by dependency and outcome
- readiness state by service
- stream interruption count
- tool execution count by adapter and outcome

Current implemented baseline:

- `agent-api` exposes `GET /metrics` with Prometheus-compatible text output
- implemented first-wave series currently cover:
  - `agent_api_http_request_total`
  - `agent_api_http_request_duration_seconds`
  - `agent_api_chat_runtime_total`
  - `agent_api_chat_runtime_duration_seconds`
  - `agent_api_chat_storage_total`
  - `agent_api_tool_execution_total`
  - `agent_api_tool_audit_total`
  - `agent_api_readiness_total`

Metric labels are intentionally low-cardinality.

Examples:

- request metrics group paths into stable route families such as
  `chat_completions`, `readyz`, and `models`
- tool metrics label fixed `tool_name` values and coarse `error_type`
- chat runtime metrics label `public_model`, `phase`, and `outcome`

## Failure investigation order

1. check `readyz` for the serving component
2. find the `request_id`
3. inspect dependency call results for that request
4. inspect persistence and completion events
5. use smoke and rollback runbooks if the issue is deployment-wide

## Relation to smoke tests

Smoke tests validate the observable contract rather than implementation details.

At minimum they should verify:

- `healthz`
- `readyz`
- one successful chat request
- one persisted interaction
- optional feature checks only when those features are enabled in that environment
