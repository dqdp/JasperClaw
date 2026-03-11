#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"
if [[ "${PYTHON_BIN}" != /* ]]; then
  PYTHON_BIN="${REPO_ROOT}/${PYTHON_BIN}"
fi

services=(
  "services/agent-api"
  "services/stt-service"
  "services/tts-service"
  "services/tools-gateway"
)

for service in "${services[@]}"; do
  if [[ -d "${service}/tests" ]]; then
    echo "==> pytest ${service}"
    (
      cd "${service}"
      "${PYTHON_BIN}" -m pytest tests
    )
  fi
done
