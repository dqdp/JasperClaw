# ADR 0009: Use a Narrow Auth and Secret Boundary for v1

- Status: Accepted
- Date: 2026-03-11

## Context

The deployment target is a single host with private Docker networks.

The system still needs a clear security boundary between the user-facing UI and the canonical backend ingress, plus explicit ownership of secrets for external integrations and runtime dependencies.

## Decision

Use a **narrow, explicit auth boundary** in v1.

### `Open WebUI -> agent-api`

Authenticate with a shared internal API credential.

### `agent-api -> internal runtime dependencies`

Trust the private network boundary in v1 rather than introducing full service-to-service authentication.

### Secret ownership rule

Each secret belongs only to the service that directly uses it.

`Open WebUI` must not hold external tool credentials, model runtime credentials, or canonical backend secrets.

## Consequences

### Positive

- keeps the critical ingress boundary explicit
- avoids unnecessary auth-system complexity for a single-host v1
- keeps privileged secrets out of the UI layer

### Negative

- internal services rely on network isolation more than a zero-trust design would
- `agent-api` becomes a concentrated secret owner in v1
- future multi-client or multi-host expansion will require a stronger auth model
