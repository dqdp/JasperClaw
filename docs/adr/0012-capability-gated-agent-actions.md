# ADR 0012: Keep Agent Actions Capability-Gated, Least-Privilege, and Audit-First

- Status: Accepted
- Date: 2026-03-11

## Context

The project is intended to grow from simple text chat toward richer tools, memory, and later automation.

That creates a real risk of accidentally giving the assistant too much freedom through loosely defined tools, hidden side effects, or arbitrary execution paths.

The system already assumes:

- `agent-api` is the canonical control plane
- tools are a typed internal boundary in v1
- secrets and privileged integrations live behind `agent-api`
- execution audit is canonical state, not an optional logging feature

What is still missing is one explicit architectural rule for how agent actions are allowed to happen at all.

## Decision

Keep all agent actions **capability-gated, least-privilege, and audit-first**.

### Capability rule

An agent may perform only actions that are exposed as explicit capabilities.

If a capability is not explicitly defined, it is forbidden by default.

### Least-privilege rule

Every capability must declare the narrowest scope required to perform its job.

Capabilities must not receive broader filesystem, network, credential, or mutation access than is required for their declared purpose.

### Audit-first rule

Every action with meaningful execution semantics must produce auditable records or structured logs with stable identifiers and outcome classification.

If an action cannot be audited, it should not be part of the canonical assistant path.

### Typed-tools preference

Typed internal tools are the preferred execution mechanism for assistant actions.

General-purpose execution paths such as arbitrary shell access are not part of the canonical product assistant path in v1.

### Approval rule

Higher-risk actions require stronger controls.

At minimum:

- read-only actions may be automatically allowed
- state-changing actions require explicit capability metadata and policy evaluation
- destructive, secret-touching, production-affecting, or externally irreversible actions require explicit approval or remain forbidden in v1

### Sandbox rule

Sandboxing is part of the execution policy, not a convenience feature.

Capability scope, network reachability, write permissions, and secret access must all be constrained by the active sandbox or execution mode.

## Consequences

### Positive

- keeps assistant behavior predictable and reviewable
- prevents tool growth from turning into implicit arbitrary execution
- aligns tools, audit, policy, and secret ownership under one model
- creates a clean future path for richer automation without dropping control

### Negative

- adds design overhead to every new capability
- slows down ad hoc integrations that would be faster as raw scripts
- requires explicit policy metadata and audit fields rather than informal conventions
