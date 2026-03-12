#!/usr/bin/env bash
set -euo pipefail

docker compose --env-file .env -f infra/compose/compose.yml -f infra/compose/compose.prod.yml pull
docker compose --env-file .env -f infra/compose/compose.yml -f infra/compose/compose.prod.yml up -d postgres ollama stt-service tts-service
COMPOSE_OVERRIDE_FILE=infra/compose/compose.prod.yml bash infra/scripts/ensure-ollama-models.sh
docker compose --env-file .env -f infra/compose/compose.yml -f infra/compose/compose.prod.yml run --rm --no-deps agent-api python -m app.cli migrate
docker compose --env-file .env -f infra/compose/compose.yml -f infra/compose/compose.prod.yml up -d --remove-orphans agent-api open-webui caddy
bash infra/scripts/smoke.sh
