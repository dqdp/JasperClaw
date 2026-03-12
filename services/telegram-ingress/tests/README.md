# Telegram Ingress Tests

Purpose:
This directory contains service-local tests for webhook handling, polling, alert relay, client behavior, and request correlation.

Start here:
- `test_main.py`: open first for most ingress behavior changes.

Index:
- `test_agent_api_client.py`: open when changing how Telegram ingress calls `agent-api` or carries request context.
- `test_main.py`: open when changing webhook auth, polling, bridge logic, commands, alerting, or structured logs.
- `test_telegram_client.py`: open when changing low-level Telegram client behavior or error handling.
