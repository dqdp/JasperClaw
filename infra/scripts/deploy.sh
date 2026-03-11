#!/usr/bin/env bash
set -euo pipefail

docker compose -f infra/compose/compose.yml -f infra/compose/compose.prod.yml pull
docker compose -f infra/compose/compose.yml -f infra/compose/compose.prod.yml up -d --remove-orphans
bash infra/scripts/smoke.sh
