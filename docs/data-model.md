# Data Model

## Purpose

Define the canonical v1 persistence model for `local-assistant`.

This document turns ADR 0005 into an implementation-oriented schema specification for:

- transcript state
- execution audit state
- derived memory and retrieval state

## Scope

This document covers the data owned by `agent-api` and persisted in `Postgres + pgvector`.

It does not make `Open WebUI` state canonical.

It also does not fully specify long-term document ingestion or voice-specific storage beyond the places where those future features touch the core model.

## Canonical state formula

Use this model consistently:

- transcript is the append-oriented source record of interaction
- execution audit is the source record of system and tool activity
- derived memory is revisable projection state, not immutable truth

## Design principles

- transcript is canonical
- execution audit is canonical
- memory is derived
- UI identifiers are metadata, not ownership
- stable public profiles are persisted separately from runtime-specific model identifiers
- deletion, retention, and provenance must remain explicit

## Logical layers

### 1. Transcript layer

Canonical source of truth for normalized assistant interactions.

Tables:

- `conversations`
- `messages`

### 2. Execution audit layer

Canonical source of truth for model and tool execution behavior.

Tables:

- `model_runs`
- `tool_executions`

### 3. Derived cognition layer

Derived state used for memory and retrieval.

Tables:

- `memory_items`
- `retrieval_runs`
- `retrieval_hits`

## ID and timestamp conventions

Recommended conventions:

- use UUID primary keys for all canonical entities
- store timestamps as `timestamptz`
- include `created_at` on all tables
- include `updated_at` on mutable tables

Soft deletion is preferred over hard deletion for canonical tables unless an explicit forget or purge flow requires physical removal.

## Table specifications

## `assistant_profiles`

Purpose:

- persist stable public profile identifiers and their policy-facing metadata

Required fields:

- `id`
- `profile_id`
- `display_name`
- `is_active`
- `created_at`
- `updated_at`

Recommended fields:

- `description`
- `quality_tier`
- `latency_tier`
- `default_temperature`
- `supports_streaming`

Notes:

- `profile_id` is the public stable identifier such as `assistant-v1`
- runtime-specific target data may live here in v1 or in a closely related config table later

## `principals`

Purpose:

- represent backend-known assistant principals or future user-facing identities relevant to canonical state

Required fields:

- `id`
- `principal_key`
- `created_at`
- `updated_at`

Recommended fields:

- `display_name`
- `status`
- `metadata_json`

Notes:

- v1 can keep this minimal
- if only one assistant principal exists initially, the table still provides a stable anchor for future expansion

## `conversations`

Purpose:

- represent canonical backend conversation groupings

Required fields:

- `id`
- `principal_id`
- `profile_id`
- `source`
- `created_at`
- `updated_at`

Recommended fields:

- `client_source`
- `client_conversation_id`
- `title`
- `status`
- `last_message_at`
- `metadata_json`
- `deleted_at`

Notes:

- `client_conversation_id` may reference a UI-side chat identifier but must not become the canonical primary key
- `source` distinguishes where the conversation originated, for example `open_webui`, `api`, or `future_mobile`

## `messages`

Purpose:

- store normalized transcript messages for a canonical conversation

Required fields:

- `id`
- `conversation_id`
- `role`
- `content_text`
- `sequence_no`
- `created_at`

Recommended fields:

- `content_json`
- `author_kind`
- `client_message_id`
- `reply_to_message_id`
- `token_count`
- `status`
- `deleted_at`
- `metadata_json`

Notes:

- `role` should align with the normalized assistant transcript, for example `system`, `user`, `assistant`, and later `tool`
- `sequence_no` must be unique within a conversation
- `content_text` is the canonical searchable human-readable form
- `content_json` can preserve richer structured content without making the raw client payload canonical

## `model_runs`

Purpose:

- audit every model invocation made as part of request orchestration

Required fields:

- `id`
- `conversation_id`
- `request_id`
- `profile_id`
- `runtime_provider`
- `runtime_model`
- `status`
- `started_at`
- `finished_at`
- `created_at`

Recommended fields:

- `input_message_id`
- `output_message_id`
- `latency_ms`
- `prompt_tokens`
- `completion_tokens`
- `total_tokens`
- `error_type`
- `error_code`
- `request_snapshot_json`
- `response_snapshot_json`

Notes:

- `runtime_model` is internal and may differ from the public profile identifier
- a failed run should still produce an audit record
- `request_id` ties the run back to request tracing and structured logs

## `tool_executions`

Purpose:

- audit every tool invocation made by the orchestration layer

Required fields:

- `id`
- `conversation_id`
- `request_id`
- `tool_name`
- `status`
- `started_at`
- `finished_at`
- `created_at`

Recommended fields:

- `model_run_id`
- `trigger_message_id`
- `latency_ms`
- `error_type`
- `error_code`
- `request_payload_json`
- `response_payload_json`
- `policy_decision`
- `adapter_name`

Notes:

- tool audit belongs here, not only in logs
- `tool_name` should be stable at the product-contract level, for example `web-search`
- `adapter_name` can hold provider-specific implementation details

## `memory_items`

Purpose:

- store derived long-lived assistant memory with provenance

Required fields:

- `id`
- `principal_id`
- `kind`
- `scope`
- `content`
- `status`
- `source_message_id`
- `created_at`
- `updated_at`

Recommended fields:

- `conversation_id`
- `confidence`
- `embedding`
- `embedding_model`
- `expires_at`
- `invalidated_at`
- `metadata_json`

Notes:

- `kind` can distinguish facts, preferences, reminders-to-self, and similar categories
- `scope` should remain explicit, for example `global`, `principal`, or later `workspace`
- `embedding` can live directly on `memory_items` in v1 via `pgvector`
- memory without provenance should be considered invalid

## `retrieval_runs`

Purpose:

- record each retrieval attempt used to assemble assistant context

Required fields:

- `id`
- `conversation_id`
- `request_id`
- `query_text`
- `created_at`

Recommended fields:

- `profile_id`
- `strategy`
- `top_k`
- `status`
- `latency_ms`
- `metadata_json`

Notes:

- retrieval runs are operational traces, not canonical transcript
- retention may be shorter than for conversations and messages

## `retrieval_hits`

Purpose:

- record which memory items were returned for a retrieval run

Required fields:

- `id`
- `retrieval_run_id`
- `memory_item_id`
- `rank`
- `score`
- `created_at`

Recommended fields:

- `selection_reason`
- `included_in_prompt`
- `metadata_json`

Notes:

- `rank` should be unique within a retrieval run
- storing `included_in_prompt` makes later evaluation easier

## `tool_credentials`

Purpose:

- track tool credential references without making raw secrets part of general query paths

Required fields:

- `id`
- `credential_key`
- `owner_service`
- `status`
- `created_at`
- `updated_at`

Recommended fields:

- `provider`
- `last_rotated_at`
- `metadata_json`

Notes:

- this table should store references and metadata, not plaintext secret values
- secret material should remain in the service-owned secret layer, not normal application rows

## `document_sources`

Purpose:

- reserve a canonical anchor for future document ingestion

Required fields:

- `id`
- `principal_id`
- `source_type`
- `status`
- `created_at`
- `updated_at`

Recommended fields:

- `external_ref`
- `title`
- `checksum`
- `metadata_json`

Notes:

- this table can remain mostly unused in early v1
- it exists to keep future document ingestion aligned with the same canonical ownership model

## `document_chunks`

Purpose:

- reserve storage for future chunked retrieval from ingested documents

Required fields:

- `id`
- `document_source_id`
- `chunk_index`
- `content`
- `created_at`

Recommended fields:

- `embedding`
- `embedding_model`
- `token_count`
- `metadata_json`

Notes:

- document chunk retrieval is not required for the first text-path delivery
- keep this schema domain optional until document ingestion is actually implemented

## Relationships

Required relationship rules:

- one `principal` can own many `conversations`
- one `conversation` can own many `messages`
- one `conversation` can have many `model_runs`
- one `conversation` can have many `tool_executions`
- one `message` can be the provenance source for many `memory_items`
- one `retrieval_run` can have many `retrieval_hits`
- one `memory_item` can appear in many `retrieval_hits`

Recommended foreign-key shape:

- `conversations.principal_id -> principals.id`
- `conversations.profile_id -> assistant_profiles.profile_id`
- `messages.conversation_id -> conversations.id`
- `model_runs.conversation_id -> conversations.id`
- `model_runs.input_message_id -> messages.id`
- `model_runs.output_message_id -> messages.id`
- `tool_executions.conversation_id -> conversations.id`
- `tool_executions.model_run_id -> model_runs.id`
- `tool_executions.trigger_message_id -> messages.id`
- `memory_items.principal_id -> principals.id`
- `memory_items.conversation_id -> conversations.id`
- `memory_items.source_message_id -> messages.id`
- `retrieval_runs.conversation_id -> conversations.id`
- `retrieval_hits.retrieval_run_id -> retrieval_runs.id`
- `retrieval_hits.memory_item_id -> memory_items.id`
- `document_sources.principal_id -> principals.id`
- `document_chunks.document_source_id -> document_sources.id`

## Indexing guidance

Minimum indexes:

- `conversations(principal_id, created_at desc)`
- `conversations(client_source, client_conversation_id)`
- `messages(conversation_id, sequence_no)`
- `model_runs(request_id)`
- `model_runs(conversation_id, started_at desc)`
- `tool_executions(request_id)`
- `tool_executions(conversation_id, started_at desc)`
- `memory_items(principal_id, kind, status)`
- `memory_items(source_message_id)`
- `retrieval_runs(request_id)`
- `retrieval_hits(retrieval_run_id, rank)`

Vector indexes:

- add a vector index only for `memory_items.embedding` when memory retrieval is actually enabled
- do not introduce unnecessary vector indexes before retrieval behavior exists

## Retention and deletion rules

### Canonical transcript and audit

Tables:

- `conversations`
- `messages`
- `model_runs`
- `tool_executions`

Rule:

- preserve by default
- prefer soft deletion for user-facing forget flows
- hard deletion should be explicit and deliberate

### Derived retrieval traces

Tables:

- `retrieval_runs`
- `retrieval_hits`

Rule:

- may use shorter retention than canonical transcript
- may be pruned operationally once they no longer serve debugging or evaluation needs

### Memory

Tables:

- `memory_items`

Rule:

- can be invalidated independently of transcript deletion
- must keep provenance while active
- `expires_at` and `invalidated_at` should make memory lifecycle explicit

## Migration strategy

Rules for v1:

- use forward-only schema migrations
- avoid destructive migrations on canonical transcript tables unless operationally planned
- add columns as nullable first when backward compatibility matters
- do not drop provenance fields casually
- treat vector storage changes as schema changes with rollout implications

## Explicitly deferred

- full per-user auth and tenancy modeling
- finalized document retrieval schema behavior
- finalized voice artifact storage
- background compaction or summarization tables
- automatic memory materialization from every message by default

## Implementation priority

When turning this into code, prioritize in this order:

1. `assistant_profiles`
2. `principals`
3. `conversations`
4. `messages`
5. `model_runs`
6. `tool_executions`
7. `memory_items`
8. `retrieval_runs`
9. `retrieval_hits`

`tool_credentials`, `document_sources`, and `document_chunks` can remain skeletal until the corresponding features are implemented.
