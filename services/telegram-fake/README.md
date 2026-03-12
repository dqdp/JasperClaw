# Telegram Fake

Purpose:
This is a test-only fake Telegram Bot API service used by CI and smoke validation for `telegram-ingress`.

Start here:
- `app/main.py`: open first for the fake Bot API contract and inspection endpoints.

Index:
- `Dockerfile`: open when changing how the fake service is built in CI.
- `pyproject.toml`: open when changing pytest or local project metadata.
- `requirements.txt`: open when changing runtime Python dependencies.
- `app/`: open when changing fake Telegram API behavior or inspection controls.
- `tests/`: open when changing coverage for the fake service itself.

Notes:
- This service exists only to support deterministic smoke and test flows.
