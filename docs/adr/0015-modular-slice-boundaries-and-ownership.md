# ADR 0015: Enforce Modular Slice Boundaries and Explicit Ownership

- Status: Accepted
- Date: 2026-03-13

## Context

The repository already has the correct high-level v1 architecture:

- `agent-api` is the canonical AI/control-plane ingress
- `Postgres` is the canonical state store
- `telegram-ingress` is a channel adapter, not the canonical assistant backend
- tools remain in-process in `agent-api` in v1

However, the current implementation is accumulating large orchestration modules and
blurred ownership boundaries:

- `agent-api` contains large application and persistence aggregators
- `telegram-ingress` contains transport, planning, worker, and persistence
  orchestration in the same slice
- some database ownership is implicit rather than explicit
- adding new channels, runtimes, or tools risks expanding existing God objects
  instead of extending stable module seams

If this continues, the project will remain operationally simple at the
deployment layer but become structurally difficult to evolve safely.

## Decision

Keep the current service topology, but enforce strict internal modular
boundaries.

### Core rule

Complex logic must sit behind simple facades.

That means:

- transport layers stay thin
- each public endpoint calls a small application facade
- facades orchestrate use cases but do not absorb all policy, parsing,
  persistence, and adapter logic
- persistence ownership is explicit per concern
- background workers call explicit `run_once()` or equivalent application
  entrypoints

## Service-level architecture

### `agent-api`

`agent-api` remains the only canonical AI/backend control plane.

It owns:

- chat orchestration
- conversation continuity
- memory retrieval and materialization
- tool policy and execution orchestration
- readiness
- canonical transcript and audit persistence

It must be internally decomposed into bounded slices.

Target slices:

- `chat`
- `conversations`
- `memory`
- `tools`
- `audit`
- `readiness`

### `telegram-ingress`

`telegram-ingress` remains a channel-specific adapter service.

It owns:

- Telegram update ingress
- Telegram reply bridge behavior
- Telegram operational alert intake and fanout
- Telegram-specific retry/dedupe worker logic

It must not become a second canonical assistant control plane.

Target slices:

- `webhook`
- `alerts`
- `lifecycle`

## Internal structure rules

### Transport

HTTP routers and app entrypoints may:

- validate transport input
- read headers
- map transport errors
- call one application facade

HTTP routers and app entrypoints may not:

- implement planning logic
- implement retry policy
- implement SQL transitions
- contain long-running workflow logic
- contain business normalization rules beyond thin transport adaptation

### Application facades

An application facade owns:

- use-case orchestration
- sequencing across collaborators
- final result assembly

An application facade does not own:

- raw SQL
- provider-specific protocol mapping
- reusable parsing or formatting logic
- static policy catalogs
- background loop control

### Repositories

Repositories are scoped by persistence concern, not by entire service.

A repository should own one of:

- conversation persistence
- transcript persistence
- model-run audit
- memory retrieval or materialization persistence
- tool execution audit
- alert outbox persistence

A repository should not own all service persistence concerns at once.

### Adapters

Provider and client adapters own:

- provider protocol mapping
- request and response normalization
- timeout and retry translation
- provider-specific error mapping

Adapters do not own application policy or persistence.

## Ownership policy

Ownership must be explicit across four dimensions:

- runtime owner
- code owner
- table owner
- migration owner

Example ownership matrix:

| Concern | Runtime owner | Code owner | Table owner | Migration owner |
|---|---|---|---|---|
| chat completions | `agent-api` | `agent-api/chat` | `agent-api` | shared db runner with explicit `agent-api` ownership |
| conversation continuity | `agent-api` | `agent-api/conversations` | `agent-api` | shared db runner with explicit `agent-api` ownership |
| memory retrieval and materialization | `agent-api` | `agent-api/memory` | `agent-api` | shared db runner with explicit `agent-api` ownership |
| tool execution audit | `agent-api` | `agent-api/tools` and `agent-api/audit` | `agent-api` | shared db runner with explicit `agent-api` ownership |
| Telegram webhook bridge | `telegram-ingress` | `telegram-ingress/webhook` | none unless later persisted | n/a |
| Telegram alert outbox | `telegram-ingress` | `telegram-ingress/alerts` | `telegram-ingress` | shared db runner with explicit `telegram-ingress` ownership |

## Database and migration policy

Database migrations remain forward-only.

But migration authority must no longer be implicitly attached to whichever
service currently happens to run the migration command.

Accepted direction:

- use a neutral migration runner boundary for shared Postgres administration
- annotate migration ownership per table group
- avoid placing one service's runtime-owned tables under another service's
  implicit domain ownership

This preserves a shared physical database without creating shared logical
ownership.

## Target package shape

### `agent-api`

Recommended internal shape:

- `api/routers/*`
- `bootstrap/*`
- `modules/chat/*`
- `modules/conversations/*`
- `modules/memory/*`
- `modules/tools/*`
- `modules/audit/*`
- `modules/readiness/*`
- `persistence/*`

### `telegram-ingress`

Recommended internal shape:

- `api/routers/*`
- `bootstrap/*`
- `modules/webhook/*`
- `modules/alerts/*`
- `persistence/*`

## Consequences

### Positive

- preserves the current high-level architecture
- makes new channels easier to add as thin adapters
- makes new runtime and model adapters easier to add without touching transport
  code
- reduces God object growth
- improves layer-specific testing
- makes database ownership and migration review more defensible

### Negative

- introduces more modules and wiring
- requires careful refactoring to avoid behavioral drift
- may initially feel slower than adding features directly into existing large
  services

## Explicit non-decisions

This ADR does not:

- add new network services
- introduce an event bus
- introduce Kubernetes
- extract tools into a standalone service in v1
- make `telegram-ingress` a canonical backend surface
- require separate databases per service

## Implementation guidance

Refactoring should proceed in phases.

### Phase 1

Stabilize facades without changing public contracts.

- introduce thin application facades
- keep existing behavior intact
- move transport-only logic out of service internals where needed

### Phase 2

Split large orchestration modules into slice-local collaborators.

- parsing
- policy
- planning
- execution
- audit recording

### Phase 3

Split large repositories by persistence concern.

- conversations
- transcript
- memory
- tool audit
- alert outbox

### Phase 4

Move migration execution to a neutral database administration boundary with
explicit ownership metadata.

## Acceptance criteria

This ADR is considered implemented when:

- public HTTP contracts remain unchanged
- each public route delegates to a small facade
- no single application service mixes transport, policy, provider adaptation,
  and persistence logic
- repositories are scoped by concern rather than by entire service
- table and migration ownership are explicit
- new channel adapters can be added without modifying core chat orchestration
  internals
- new runtime and model adapters can be added without modifying HTTP transport
  layers
