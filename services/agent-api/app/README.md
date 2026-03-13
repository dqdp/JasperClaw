# Agent API App

Purpose:
This directory contains the application code for the canonical control-plane service.

Start here:
- `main.py`: open first for app construction, middleware, and top-level router wiring.

Index:
- `api/`: open when changing HTTP route wiring, dependencies, or transport-level behavior.
- `cli.py`: open when changing migration or admin CLI entrypoints.
- `clients/`: open when changing Ollama, search, or Spotify dependency adapters.
- `core/`: open when changing auth, config, logging, or error infrastructure.
- `migrations/`: open when changing the service-local migration shim or readiness integration.
- `repositories/`: open when changing Postgres persistence and audit writes.
- `schemas/`: open when changing request/response validation models.
- `services/`: open when changing chat orchestration or readiness logic.
