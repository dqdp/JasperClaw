# Dashboard and Alert Rollout

## Purpose

Define the first practical dashboards and alert rules for the currently
implemented metrics in `agent-api` and `telegram-ingress`.

This document is intentionally operational.

It is not a generic observability philosophy note.

It answers:

- which dashboards should exist first
- which metric families belong on each dashboard
- which alert rules are worth enabling first
- which signals are expected noise versus real degradation

## Scope

This rollout plan covers only currently implemented process metrics:

- `agent-api`
- `telegram-ingress`

It does not yet define:

- distributed tracing rollout
- host-level resource dashboards
- `stt-service` or `tts-service` dashboards
- Open WebUI dashboards
- deep database internals dashboards

## Runnable stack

The runnable Prometheus and Grafana stack for this rollout lives under
`infra/compose/observability/` and is started through the Compose
`observability` profile.

The provisioned artifacts are:

- Prometheus scrape config in `infra/compose/observability/prometheus/prometheus.yml`
- alert rules in `infra/compose/observability/prometheus/alerts/`
- Grafana datasource provisioning in `infra/compose/observability/grafana/provisioning/`
- Grafana dashboards in `infra/compose/observability/grafana/dashboards/`

## Dashboard set

Create three dashboards.

### 1. Agent API: Core Control Plane

Purpose:

- answer whether the canonical text path is healthy
- distinguish request-path, runtime, storage, and readiness failures quickly

Panels:

- `agent_api_http_request_total` grouped by `path_group`, split by `status_class`
- p50/p95 `agent_api_http_request_duration_seconds` grouped by `path_group`
- `agent_api_chat_runtime_total` split by `outcome` and `phase`
- p50/p95 `agent_api_chat_runtime_duration_seconds`
- `agent_api_chat_storage_total` split by `outcome`
- `agent_api_readiness_total` split by `status`

Interpretation:

- rising `5xx` on `chat_completions` plus runtime errors usually means core-path degradation
- rising `chat_storage_total{outcome="error"}` points to persistence problems
- `readiness_total{status="not_ready"}` is a service-level incident signal, not a feature-level warning

### 2. Agent API: Tools And Memory

Purpose:

- separate optional augmentation-path degradation from core control-plane failures

#### Tools section

Panels:

- `agent_api_tool_execution_total` by `tool_name` and `outcome`
- `agent_api_tool_execution_total` by `tool_name` and `error_type`
- `agent_api_tool_audit_total` by `outcome`

Interpretation:

- `policy_error` tool failures are expected in some request paths and should not alert by default
- `tool_audit_total{outcome="error"}` is more important than raw tool execution failure volume
- tool-path failures with stable core runtime indicate optional-path degradation, not total outage

#### Memory section

Panels:

- `agent_api_memory_retrieval_total` by `outcome`
- p50/p95 `agent_api_memory_retrieval_duration_seconds`
- `agent_api_memory_retrieval_hits_total`
- `agent_api_memory_embedding_total` by `phase` and `outcome`
- `agent_api_memory_audit_total` by `outcome`
- `agent_api_memory_materialization_total` by `outcome`
- p50/p95 `agent_api_memory_materialization_duration_seconds`

Interpretation:

- `skipped` is expected when memory is disabled or the request is not eligible
- `empty` is not automatically a problem; it often means retrieval found no relevant prior context
- `error` on retrieval, embedding, or materialization is the primary degradation signal
- rising memory audit errors means observability or persistence debt in the memory path, not necessarily retrieval failure itself

### 3. Telegram Operations

Purpose:

- observe the Telegram channel adapter and durable alert-delivery path independently from the main control plane

Panels:

- `telegram_alert_delivery_claim_total` by `origin`
- `telegram_alert_delivery_claim_skipped_total`
- `telegram_alert_delivery_target_attempt_total` by `status` and `error_class`
- `telegram_alert_delivery_target_attempt_persist_failed_total`
- `telegram_alert_delivery_finalize_total` by `status`
- `telegram_alert_delivery_finalize_failed_total`

Interpretation:

- `claim_total{origin="stale_reclaim"}` reflects recovery pressure after claim expiry
- `target_attempt_total{status="pending",error_class="http_429"}` reflects Telegram backpressure
- finalize or persist failures point to durability-boundary problems rather than pure transport issues

## Alert rules

Enable alerts in two stages.

### Stage 1: critical only

#### Agent API critical alerts

- sustained growth of `agent_api_readiness_total{status="not_ready"}` for 5 minutes
- sustained increase of `agent_api_http_request_total{path_group="chat_completions",status_class="5xx"}`
- sustained increase of `agent_api_chat_storage_total{outcome="error"}`

#### Telegram critical alerts

- sustained increase of `telegram_alert_delivery_finalize_failed_total`
- sustained increase of `telegram_alert_delivery_target_attempt_persist_failed_total`

### Stage 2: warning alerts

#### Agent API warnings

- elevated ratio of `agent_api_chat_runtime_total{outcome="error"}` to total runtime completions
- sustained increase of `agent_api_tool_audit_total{outcome="error"}`
- sustained increase of `agent_api_memory_retrieval_total{outcome="error"}`
- sustained increase of `agent_api_memory_materialization_total{outcome="error"}`
- sustained increase of `agent_api_memory_embedding_total{outcome="error",phase="retrieve"}`
- sustained increase of `agent_api_memory_embedding_total{outcome="error",phase="store"}`

#### Telegram warnings

- stale reclaim ratio becomes materially higher than baseline
- sustained increase of `telegram_alert_delivery_target_attempt_total{status="pending",error_class="http_429"}`

## Signals that should not alert first

Avoid alerting on these in the first rollout:

- individual tool execution failures
- expected policy denials such as Telegram-originated tool blocks
- isolated Telegram retryable failures
- high `memory_retrieval_total{outcome="empty"}` without accompanying latency or error changes
- high `memory_retrieval_total{outcome="skipped"}` when memory is intentionally disabled in the deployment

## Rollout order

1. Create `Agent API: Core Control Plane`.
2. Create `Telegram Operations`.
3. Create `Agent API: Tools And Memory`.
4. Observe dashboards without alerts for 3 to 7 days to establish baseline behavior.
5. Enable only critical alerts first.
6. Enable warning alerts after baseline review.

## Operational notes

- prefer ratios and sustained growth over single-event alerts
- keep labels low-cardinality in dashboards as well as alert rules
- treat tools and memory as important but non-core unless they begin to affect the canonical text-path SLO
- revisit thresholds after the first production baseline period instead of trying to perfect them upfront
