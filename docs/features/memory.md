# Memory

## Purpose

Define the canonical v1 memory model for `local-assistant` and explain how memory fits into the text-serving path without becoming the source of truth.

This document builds on:

- `ADR 0005`
- `docs/data-model.md`
- `docs/features/chat.md`

## Core rule

Memory is **derived**, not canonical.

The canonical source of truth remains:

- transcript as the source interaction record
- execution audit as the source execution record

Memory exists as revisable derived state to improve future responses, not to replace stored conversation history.

## Goals

- preserve useful long-lived context across sessions
- make retrieval explicit and auditable
- keep provenance to source messages
- allow invalidation and expiry without corrupting transcript history

## Non-goals for early v1

- summarizing every message automatically
- building a generic knowledge graph
- turning memory into a second transcript system
- storing UI-owned chat state as memory

## Memory lifecycle

### 1. Source transcript exists first

Memory can only be created from canonical transcript state that already exists in:

- `conversations`
- `messages`

### 2. Candidate extraction

The system identifies memory candidates from transcript messages.

Typical candidates:

- stable preferences
- recurring facts about the principal
- durable context that may matter in later sessions

Non-candidates:

- transient acknowledgements
- low-signal chatter
- content with no clear future value

### 3. Memory materialization

A valid memory item is written to `memory_items` only if:

- it has provenance
- it has explicit scope
- it has explicit lifecycle state

### 4. Retrieval

At request time, retrieval may search memory for relevant context.

That process should produce:

- one `retrieval_run`
- zero or more `retrieval_hits`

### 5. Invalidation or expiry

Memory can later be:

- invalidated
- superseded
- expired
- explicitly deleted through a future forget flow

## Canonical memory fields

The memory model should preserve:

- `kind`
- `scope`
- `content`
- `source_message_id`
- `conversation_id` when useful
- `confidence`
- `status`
- `embedding`
- `embedding_model`
- `expires_at`
- `invalidated_at`

## Provenance rule

Memory without provenance is not acceptable as canonical derived state.

At minimum each active memory item must point back to:

- one source message

Recommended:

- also preserve conversation linkage and extraction metadata

## Scope rule

Memory must always have explicit scope.

Recommended early scopes:

- `principal`
- `global`

Do not leave scope implicit.

## Status rule

Memory should have explicit lifecycle state.

Longer-term target states:

- `active`
- `expired`
- `invalidated`
- `deleted`

Current schema-constrained contract:

- `active`
- `invalidated`
- `deleted`

The current implemented schema does not yet carry an `expires_at` field, so
automatic `expired` handling is deferred until a follow-on schema slice adds
explicit TTL state instead of inferring it implicitly.

## Confidence rule

Memory extraction is not guaranteed to be correct.

The system should therefore preserve confidence or quality metadata rather than pretending all memory is equally reliable.

This does not have to be perfect in the first implementation, but it should be designed for.

## Retrieval behavior

Retrieval should be:

- optional by profile or deployment stage
- bounded by explicit `top_k`
- observable through `retrieval_runs` and `retrieval_hits`

Retrieval must not silently mutate transcript state.

## Prompt assembly rule

Retrieved memory is prompt context, not rewritten conversation history.

The model should receive:

- canonical current transcript
- optional selected memory context

The system should not merge memory back into stored messages as if it had originally been part of the transcript.

## Retention and deletion

### Transcript

Transcript remains canonical and is retained under transcript rules.

### Memory

Memory can have a shorter or more selective lifecycle than transcript.

Key rules:

- expiry must be explicit
- invalidation must be explicit
- deletion should not erase the fact that transcript originally existed unless a stronger purge flow requires it

Current lifecycle baseline for the next implementation slice:

- newly materialized memory is written as `active`
- retrieval must consider only `active` memory
- `invalidated` means the memory is no longer eligible for retrieval because it
  was contradicted, superseded, or otherwise judged unreliable
- `deleted` means the memory item is intentionally removed from future retrieval
  through an explicit forget or operator action, while the source transcript
  remains canonical unless a stronger purge flow is invoked
- retention is currently unbounded for `active` memory unless an explicit
  invalidation or deletion transition occurs
- automatic expiry is deferred until the schema can store explicit expiry data

## What I would not hide

- memory extraction will produce mistakes
- relevance scoring will be noisy at first
- too-aggressive memory extraction can degrade assistant quality
- storing every possible fact is worse than storing fewer, more defensible memories

## Recommended v1 rollout

1. implement transcript persistence first
2. implement `memory_items` schema second
3. start with conservative extraction rules
4. add retrieval traces before optimizing relevance
5. only later expand categories and automation

Current Memory Slice 1 baseline:

- retrieval is optional and deployment-gated
- one shared backend principal is used until request identity grows beyond the current trusted-client model
- retrieval uses the latest `user` turn as the semantic query
- `memory_items` are currently derived only from conservative `user` transcript turns
- retrieval and memory writes are fail-open relative to the core chat response path
- all materialized memory is currently written as `active`; lifecycle
  transitions beyond that state are not yet implemented

## Anti-patterns

Avoid:

- storing raw UI sessions as memory
- writing memory without provenance
- using memory as a substitute for transcript retrieval
- treating all extracted facts as permanent
- making retrieval invisible to logs and audit state
