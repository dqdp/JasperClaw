# ADR 0016: Defer Tools Gateway Extraction While Keeping `agent-api` as the Control Plane

- Status: Accepted
- Date: 2026-03-13

## Context

The project already has an accepted v1 decision:

- `agent-api` is the single canonical backend ingress
- tools remain in-process in `agent-api` in v1

At the same time, the repository still contains a legacy `services/tools-gateway/`
directory from an earlier topology idea.

This creates a real ambiguity:

- ADRs and implementation status say that tool execution is currently an
  in-process boundary inside `agent-api`
- the repository tree visually suggests that a separate tools service may already
  be part of the active runtime

That ambiguity is manageable while the tool surface is small, but it becomes more
dangerous as the number of tools grows.

The project is expected to accumulate:

- more provider adapters
- more capability and approval rules
- more execution audit requirements
- different latency and dependency profiles across tools
- possible long-running or isolated execution paths later

So the project does need a durable tools-management layer.

The architectural question is not whether such a layer is needed.

The real question is:

- should the tools-management layer already be a separate network service now
- or should it remain a logical boundary inside `agent-api` until there is a
  concrete extraction trigger

## Decision

Keep `agent-api` as the canonical tools control plane.

In the current phase:

- tool planning stays in `agent-api`
- tool policy and capability gating stay in `agent-api`
- tool approvals stay in `agent-api`
- tool audit and request correlation stay in `agent-api`
- tool execution remains an internal modular runtime boundary, not a separate
  active network service

`services/tools-gateway/` is treated as future extraction scaffold only.

It is not part of the active runtime architecture unless a later ADR explicitly
changes that status.

## Accepted shape

### `agent-api` owns

- the public tool-facing control boundary
- tool selection and planning decisions
- policy enforcement
- capability checks
- approval integration
- audit and request correlation
- stable error mapping back to clients

### The internal tools runtime owns

- provider-specific adapters
- typed execution envelopes
- timeout handling
- retry behavior where appropriate
- provider protocol normalization
- per-tool dependency handling

### Future extraction target

If a separate tools service becomes justified later, it must be an extraction of
the internal tools runtime boundary rather than a second control plane.

That means:

- clients still do not talk to tools directly
- `agent-api` still remains the only canonical public backend ingress
- policy, approvals, and audit do not become split-brain across services

## Extraction triggers

A standalone `tools-gateway` or equivalent execution service is justified only
when one or more of the following become materially true:

- tool dependency stacks become large enough to create unacceptable coupling
  inside `agent-api`
- tool execution needs stricter sandbox or worker isolation than the current
  process model can provide
- long-running or asynchronous tool jobs become common
- tool execution needs a meaningfully different scaling profile from the
  `agent-api` request path
- multiple runtime clients besides `agent-api` need the same execution plane
- tool execution inside `agent-api` creates unacceptable blast radius for the
  canonical control plane

Without those triggers, extraction is considered premature complexity.

## Consequences

### Positive

- preserves a single canonical control plane
- avoids a premature network hop and extra readiness surface
- keeps policy, approvals, and audit close to orchestration
- still allows a future extraction path if real operational pressure appears
- makes the current repository state less ambiguous to contributors

### Negative

- `agent-api` continues to own more internal tool-runtime complexity in the
  near term
- extraction, when it eventually happens, will still require deliberate
  refactoring and rollout work
- repository scaffold material must be kept clearly marked as non-canonical
  until extraction is actually authorized

## Explicit non-decisions

This ADR does not:

- remove the future possibility of a standalone tools execution service
- require extraction in v1
- allow direct client or UI access to tools outside `agent-api`
- move policy or approval ownership out of `agent-api`
- make the current `services/tools-gateway/` directory part of the active runtime

## Implementation guidance

Near-term code changes should follow these rules:

- keep the tools boundary modular inside `agent-api`
- design internal execution contracts so they are extraction-ready
- keep tool-specific dependencies behind adapters
- avoid introducing a second control boundary outside `agent-api`
- keep `services/tools-gateway/` documentation explicitly marked as future
  scaffold until a later ADR changes the runtime topology
