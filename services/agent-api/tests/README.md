# Agent API Tests

Purpose:
This directory contains service-local tests covering auth, chat flow, observability, migrations, and provider adapters.

Start here:
- `test_chat_completions.py`: open first for most request-path behavior changes.

Index:
- `conftest.py`: open when changing common test fixtures or env resets.
- `test_auth.py`: open when changing internal auth rules.
- `test_chat_completions.py`: open when changing chat behavior, tool policy, or memory flow.
- `test_chat_flow_integration.py`: open when changing end-to-end orchestration with persistence or tool audit.
- `test_cli.py`: open when changing legacy migration CLI compatibility behavior.
- `test_conversation_resolution.py`: open when changing canonical conversation reuse behavior.
- `test_health.py`: open when changing liveness endpoints.
- `test_migrations.py`: open when changing migration compatibility, canonical catalog discovery, or SQL execution ordering.
- `test_models.py`: open when changing `/v1/models`.
- `test_observability.py`: open when changing request IDs, structured logs, or audit continuity.
- `test_ollama_client.py`: open when changing Ollama client behavior or embedding parsing.
- `test_readiness.py`: open when changing downstream readiness semantics.
- `test_spotify_client.py`: open when changing Spotify adapter behavior.
