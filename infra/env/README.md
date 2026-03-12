# Env

Purpose:
This directory holds example and active env files that parameterize local, CI, and Telegram-specific runs.

Start here:
- `app.example.env`: open first for the baseline application configuration shape.

Index:
- `app.example.env`: open when checking the normal application env surface.
- `app.ci-smoke.example.env`: open when reproducing CI smoke inputs locally; this file points `OLLAMA_BASE_URL` at `ollama-fake`.
- `app.env`: open when checking the current local app env file used by scripts.
- `prod.example.env`: open when preparing production root env values.
- `root.ci-smoke.example.env`: open when checking CI root-level deploy/smoke inputs.
- `telegram.ci-smoke.example.env`: open when reproducing Telegram ingress smoke configuration with the fake Telegram service.
- `telegram.example.env`: open when configuring Telegram ingress and alert-relay variables.
