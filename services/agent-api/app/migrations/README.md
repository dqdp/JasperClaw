# Agent API Migrations

Purpose:
This directory is a compatibility shim for migration-aware readiness and legacy
service-local imports.

Start here:
- `runner.py`: open first for the service-local compatibility wrapper.

Index:
- `runner.py`: open when changing how `agent-api` discovers the canonical
  `platform-db` migration catalog.
