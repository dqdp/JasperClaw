#!/usr/bin/env bash
set -euo pipefail

docker compose --env-file .env -f infra/compose/compose.yml -f infra/compose/compose.prod.yml pull
docker compose --env-file .env -f infra/compose/compose.yml -f infra/compose/compose.prod.yml up -d --remove-orphans
bash infra/scripts/smoke.sh
