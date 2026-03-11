# ADR 0007: Keep the Tools Boundary In-Process in v1

- Status: Accepted
- Date: 2026-03-11

## Context

The repository scaffold includes a placeholder `tools-gateway` service.

For v1, the tool surface is still small, deployment is single-host, and there is no strong evidence yet that a separate network service is worth the operational cost.

## Decision

Keep the tools boundary **logical but in-process** inside `agent-api` in v1.

### `agent-api` owns

- tool policy decisions
- tool audit and request correlation
- orchestration around model and tool use

### The tools integration layer owns

- provider-specific adapters
- typed tool request and response envelopes
- timeout, retry, and error mapping behavior per integration

### Extraction rule

Design the internal tools interface so it can be extracted into a standalone `tools-gateway` later if a real operational reason appears.

## Consequences

### Positive

- avoids an unnecessary network hop in v1
- reduces deployment and readiness complexity
- keeps policy and audit close to orchestration
- still preserves a future extraction path

### Negative

- `agent-api` owns more code and more secrets in v1
- a later extraction will still be a refactor, even if the interface is prepared for it
