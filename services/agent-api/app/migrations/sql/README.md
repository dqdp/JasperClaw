# Agent API Migration SQL

Purpose:
This directory stores the forward-only SQL migration history for canonical persistence.

Start here:
- `0001_initial_schema.sql`: open first to understand the base text-path schema.

Index:
- `0001_initial_schema.sql`: open when reviewing the initial conversation/message/model-run tables.
- `0002_conversation_updates.sql`: open when reviewing continuity-related schema adjustments.
- `0003_memory_foundation.sql`: open when changing memory, embeddings, or retrieval trace tables.
- `0004_tool_execution_audit.sql`: open when changing tool execution audit persistence.
- `0005_client_conversation_bindings.sql`: open when reviewing backend-owned client session to canonical conversation bindings.
