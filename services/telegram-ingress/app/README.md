# Telegram Ingress App

Purpose:
This directory contains the application code for Telegram webhook/polling ingress and alert relay behavior.

Start here:
- `main.py`: open first for app construction and endpoint wiring.

Index:
- `clients/`: open when changing downstream calls to Telegram or `agent-api`.
- `core/`: open when changing settings or structured logging.
- `services/`: open when changing update parsing, command handling, idempotency, or bridge flow.
