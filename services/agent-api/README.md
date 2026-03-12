# Agent API

Purpose:
This service is the canonical v1 control plane for chat, retrieval, tools, persistence, and readiness.

Start here:
- `app/main.py`: open first for the FastAPI entrypoint and middleware wiring.

Index:
- `Dockerfile`: open when changing how the service is built and run in containers.
- `pyproject.toml`: open when changing pytest or local Python project metadata.
- `requirements.txt`: open when changing runtime Python dependencies.
- `app/`: open when changing HTTP routes, orchestration, clients, persistence, or migrations.
- `tests/`: open when changing service behavior and its local/unit/integration coverage.
