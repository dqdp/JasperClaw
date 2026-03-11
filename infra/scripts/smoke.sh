#!/usr/bin/env bash
set -euo pipefail

curl -fsS http://localhost/ >/dev/null || true
curl -fsS http://localhost:8080/healthz >/dev/null || true
printf 'Smoke script placeholder completed\n'
