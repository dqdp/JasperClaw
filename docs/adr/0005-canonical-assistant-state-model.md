# ADR 0005: Separate Transcript, Execution Audit, and Derived Memory State

- Status: Accepted
- Date: 2026-03-11

## Context

The system needs a canonical state model for:

- conversations and messages
- model execution and tool audit
- memory extraction and retrieval

Trying to represent all of that in one generic persistence layer would blur source-of-truth boundaries and make future retrieval, deletion, and audit behavior harder to reason about.

## Decision

Use three distinct persistence layers in v1.

### 1. Transcript layer

Canonical entities:

- `conversations`
- `messages`

This is the canonical source of truth for normalized assistant interactions.

### 2. Execution audit layer

Canonical entities:

- `model_runs`
- `tool_executions`

This is the canonical source of truth for execution history, latency, status, and audit data.

### 3. Derived cognition layer

Derived entities:

- `memory_items`
- `retrieval_runs`
- `retrieval_hits`

This layer is derived from canonical transcript and execution data. It is not a replacement for them.

### Additional rule

UI references such as client-side conversation identifiers are metadata only. They do not own canonical transcript state.

## Consequences

### Positive

- transcript, audit, and memory concerns stay separable
- retrieval can evolve without corrupting transcript ownership
- tool audit no longer depends on logs alone
- future retention and deletion rules can be more explicit

### Negative

- more schema objects exist from the start
- persistence work requires slightly more upfront design
- message embeddings are no longer treated as a one-size-fits-all storage primitive
