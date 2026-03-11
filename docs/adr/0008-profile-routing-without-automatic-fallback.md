# ADR 0008: Use Profile-Based Routing Without Automatic Runtime Fallback

- Status: Accepted
- Date: 2026-03-11

## Context

The public contract should expose stable assistant profiles such as `assistant-v1` and `assistant-fast`.

There is a risk of over-engineering a broad provider abstraction or hiding runtime problems behind silent per-request fallback logic.

## Decision

Use **profile-based routing** with a shallow provider abstraction and **no automatic per-request fallback** in v1.

### Public contract

Clients choose logical profile IDs:

- `assistant-v1`
- `assistant-fast`

### Internal mapping

Each profile resolves to one explicit internal `Ollama` runtime configuration.

### Failure rule

If the resolved runtime is unavailable, return an explicit error.

Operational fallback, if needed, is a configuration change or rollout action, not hidden per-request behavior.

## Consequences

### Positive

- keeps behavior predictable and auditable
- keeps client contracts stable
- avoids building an imaginary multi-provider platform too early
- simplifies debugging of runtime failures

### Negative

- there is less graceful degradation in v1
- future provider expansion will require a deliberate extension of the runtime layer
