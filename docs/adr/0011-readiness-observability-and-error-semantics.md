# ADR 0011: Define Core-Path Readiness, Structured Observability, and Stable Error Semantics

- Status: Accepted
- Date: 2026-03-11

## Context

The repository already assumes:

- `agent-api` is the canonical backend ingress
- the text path is the first working vertical slice
- voice and richer tool behavior arrive later

Without explicit operational semantics, health checks, smoke tests, logs, and API failures will drift into inconsistent behavior.

## Decision

Adopt a **core-path operational contract** for v1.

### Liveness

`GET /healthz` indicates only that the process is alive enough to serve traffic.

It must not depend on downstream services.

### Readiness

`GET /readyz` indicates that the **core text path** is ready to serve user traffic.

For `agent-api`, readiness must reflect:

- valid runtime configuration
- `Postgres` connectivity
- primary chat runtime availability through `Ollama`

Optional feature dependencies must not fail global readiness unless those features are explicitly required in the current deployment mode.

### Observability baseline

Every request must have a stable request identifier.

The system must emit structured logs with enough information to trace:

- ingress
- dependency calls
- persistence outcomes
- final success or failure

### Error semantics

The public API must use a stable machine-readable error envelope.

Raw provider and dependency errors must stay in internal logs rather than leaking directly to clients.

Error classification must stay stable at the type level while allowing more specific codes underneath.

## Consequences

### Positive

- health and readiness checks become meaningful rather than decorative
- smoke tests can validate the real text-serving path
- request tracing becomes possible without ad hoc log hunting
- client-visible error behavior becomes predictable

### Negative

- readiness logic becomes stricter than a placeholder success response
- structured logging and error mapping require up-front design work
- optional feature enablement must be explicit to avoid probe ambiguity
