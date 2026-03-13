# Scripts

Purpose:
This directory contains operational helper scripts for bootstrap, deploy, smoke checks, model prep, and Python service tests.

Start here:
- `deploy.sh`: open first for the deploy entrypoint used by rollout workflows.

Index:
- `bootstrap-host.sh`: open when preparing a fresh host with required runtime dependencies.
- `deploy.sh`: open when changing deployment orchestration.
- `ensure-ollama-models.sh`: open when changing model preloading for CI or deployment.
- `smoke-agent-api.py`: open when changing the canonical HTTP smoke contract for `agent-api`, including optional voice checks.
- `smoke-telegram-ingress.py`: open when changing deterministic smoke coverage for the Telegram ingress path.
- `smoke.sh`: open when changing the containerized smoke flow used after deploy.
- `test-python-services.sh`: open when changing the per-service Python test runner.
