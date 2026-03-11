# Agent Action Policy

## Purpose

Define the operational control model for agent actions in `local-assistant`.

This document turns ADR 0012 into concrete rules for capability registration, risk classification, approvals, sandboxing, and audit.

## Scope

This policy applies to:

- tool execution initiated by `agent-api`
- future automation or task execution capabilities
- any future extracted tools service if the tools boundary is moved out of process

This policy does not make arbitrary shell execution part of the canonical product assistant path in v1.

## Core rules

- Default deny: if an action is not exposed as a declared capability, it is forbidden.
- Least privilege: each capability gets the narrowest scope that can satisfy its contract.
- Audit first: side effects must be traceable through structured logs or canonical persistence.
- Typed over general: prefer typed tools over raw shell or provider-specific free-form execution.
- Explicit approval for higher risk: dangerous actions must not rely on model intent alone.

## Risk classes

### `R0`

Read-only, no side effects, low consequence if wrong.

Examples:

- deterministic formatting
- read-only retrieval from canonical state
- read-only health inspection

### `R1`

Local, reversible, bounded internal mutations.

Examples:

- writing derived assistant state
- updating cached projections
- recording audit rows

### `R2`

Trusted-boundary state changes with user-visible behavior impact.

Examples:

- invoking state-changing internal tool adapters
- changing playback state in Spotify
- modifying assistant-owned preferences or long-lived memory state

### `R3`

External side effects, third-party mutations, or actions with material user consequence.

Examples:

- sending messages to external systems
- purchasing, scheduling, or booking
- mutating user data outside the assistant's canonical store

### `R4`

Destructive, irreversible, secret-touching, production-affecting, or broad-scope actions.

Examples:

- deleting critical data
- accessing raw secret material
- broad filesystem execution
- production infrastructure mutation

## Capability classes

- `read_state`
- `write_state`
- `invoke_tool_read`
- `invoke_tool_write`
- `access_secret_reference`
- `execute_general_command`
- `mutate_production`

Not every class is allowed in every runtime mode.

## Approval matrix

| Risk class | Default rule | Notes |
| --- | --- | --- |
| `R0` | allow | Structured audit still required when part of request execution. |
| `R1` | allow with audit | Must stay inside declared internal scope. |
| `R2` | allow only through typed capability + policy evaluation | No hidden provider calls or raw execution path. |
| `R3` | explicit user approval required | Must be individually attributable and clearly described before execution. |
| `R4` | forbidden by default in v1 | If ever enabled later, require explicit approval plus stronger sandbox and operator controls. |

## Sandbox profiles

### `read-only`

Allows:

- `R0`

Forbids:

- any write or side effect

### `typed-tools-only`

Allows:

- `R0`
- `R1`
- selected `R2` typed capabilities

Forbids:

- arbitrary command execution
- undeclared external network targets
- direct raw provider calls outside registered adapters

### `internal-mutation`

Allows:

- `R0`
- `R1`
- approved `R2`

Additional requirements:

- internal state changes must be bounded to assistant-owned domains
- stable audit rows are mandatory

### `approval-required`

Allows:

- selected `R3`

Additional requirements:

- explicit user confirmation
- clear description of intended effect
- stable audit with approval source

### `forbidden`

Applies to:

- `R4` in v1 by default
- any undeclared capability

## Capability registration requirements

Every capability or tool must declare:

- `capability_id`
- `risk_class`
- `side_effecting`
- `idempotent`
- `requires_confirmation`
- `touches_secrets`
- `allowed_scopes`
- `sandbox_profile`
- `audit_fields`
- `timeout_ms`

Optional but recommended:

- `owner`
- `dependency`
- `retry_policy`

## Tool-specific requirements

For the v1 tools integration layer:

- `web-search` and `spotify-search` should normally be treated as `R0` or low `R2` depending on provider semantics
- `spotify-play`, `spotify-pause`, and `spotify-next` are state-changing and must not inherit the same retry or approval behavior as read-like tools
- provider-specific payloads are implementation details, not capability contracts

## Abort rules

Execution must stop and return a controlled failure when:

- the requested action does not map to a declared capability
- the capability would exceed its allowed scope
- the action requires confirmation and no explicit approval is present
- the action would touch secrets outside its declared secret boundary
- the runtime sandbox cannot enforce the required scope
- the action would become destructive, broad-scope, or production-affecting in v1

## Audit requirements

Every executed capability must record or emit:

- `request_id`
- `conversation_id` when present
- `model_run_id` when present
- `capability_id`
- `tool` when applicable
- `risk_class`
- `sandbox_profile`
- `approval_state`
- `outcome`
- `latency_ms`
- stable error `type` and `code` when failed

## v1 baseline

The default user-facing assistant path in v1 should run with:

- no arbitrary shell execution
- no production mutation capability
- no raw secret access as a tool result
- typed tools only
- explicit approval for any future `R3` action

## Change control

Any new `R2`, `R3`, or `R4` capability should update:

- the relevant service contract
- this policy when the control model changes
- ADRs when the architectural boundary changes
