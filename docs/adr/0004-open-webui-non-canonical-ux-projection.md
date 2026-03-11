# ADR 0004: Treat Open WebUI as a Non-Canonical UX Projection Layer

- Status: Accepted
- Date: 2026-03-11

## Context

`Open WebUI` naturally maintains its own chat, session, and interface state.

If that state is treated as canonical assistant state, the system will drift into a split-brain architecture where the UI and backend disagree about history, memory, and tool behavior.

The project has already accepted that `agent-api` is the canonical control plane.

## Decision

Treat `Open WebUI` as a **non-canonical UX projection layer**.

### `Open WebUI` owns

- UI accounts and authentication
- UI chat and session presentation state
- draft state and interface preferences
- temporary UI-only metadata

### `agent-api` owns

- canonical conversation transcript
- canonical assistant memory
- model run and tool audit state
- policy decisions and profile behavior

### v1 rule

Do **not** build bidirectional synchronization between `Open WebUI` persistence and canonical backend persistence in v1.

Client-provided message history is treated as input to `agent-api`, not as the canonical source of truth.

## Consequences

### Positive

- avoids split-brain state ownership
- keeps future non-UI clients viable
- keeps memory and audit tied to backend behavior
- reduces coupling to Open WebUI internals

### Negative

- UI-visible chat entities and backend conversations may not be one-to-one
- continuity rules between UI sessions and backend conversations must be explicit
- some UI convenience features may remain non-canonical
