# Telegram Ingress Clients

Purpose:
This directory contains downstream HTTP clients used by the Telegram bridge.

Start here:
- `telegram.py`: open first for Telegram Bot API calls.

Index:
- `agent_api.py`: open when changing how Telegram ingress calls `agent-api`.
- `telegram.py`: open when changing webhook registration, polling, or `sendMessage` calls to Telegram.
