# Telegram Ingress

Purpose:
This service bridges Telegram traffic into the canonical `agent-api` chat path and provides a separate alert relay path.

Start here:
- `app/main.py`: open first for webhook, polling, middleware, and alert endpoint wiring.

Index:
- `Dockerfile`: open when changing how this service is built and run in containers.
- `pyproject.toml`: open when changing pytest or local project metadata.
- `requirements.txt`: open when changing runtime Python dependencies.
- `app/`: open when changing ingress behavior, downstream clients, config, or bridge logic.
- `tests/`: open when changing webhook, polling, alerting, or request-correlation behavior.
