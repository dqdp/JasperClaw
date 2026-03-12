#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"
if [[ "${PYTHON_BIN}" != /* && "${PYTHON_BIN}" != */* ]]; then
  if command -v "${PYTHON_BIN}" >/dev/null 2>&1; then
    PYTHON_BIN="$(command -v "${PYTHON_BIN}")"
  elif [[ "${PYTHON_BIN}" == "python" ]] && command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN="$(command -v python3)"
  fi
elif [[ "${PYTHON_BIN}" == */* && "${PYTHON_BIN}" != /* ]]; then
  # Bare interpreter names should resolve through PATH on CI runners.
  PYTHON_BIN="${REPO_ROOT}/${PYTHON_BIN}"
fi

services=(
  "services/agent-api"
  "services/stt-service"
  "services/tts-service"
  "services/tools-gateway"
  "services/telegram-ingress"
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
