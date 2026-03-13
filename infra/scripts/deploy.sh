#!/usr/bin/env bash
set -euo pipefail

docker compose --env-file .env -f infra/compose/compose.yml -f infra/compose/compose.prod.yml pull
docker compose --env-file .env -f infra/compose/compose.yml -f infra/compose/compose.prod.yml up -d postgres ollama
COMPOSE_OVERRIDE_FILE=infra/compose/compose.prod.yml bash infra/scripts/ensure-ollama-models.sh
docker compose --env-file .env -f infra/compose/compose.yml -f infra/compose/compose.prod.yml build platform-db
docker compose --env-file .env -f infra/compose/compose.yml -f infra/compose/compose.prod.yml run --rm --no-deps platform-db python -m platform_db.cli migrate
docker compose --env-file .env -f infra/compose/compose.yml -f infra/compose/compose.prod.yml up -d --remove-orphans agent-api telegram-ingress open-webui caddy
bash infra/scripts/smoke.sh
