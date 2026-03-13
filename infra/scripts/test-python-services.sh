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
  "services/ollama-fake"
  "services/telegram-fake"
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

if [[ -d "platform_db/tests" ]]; then
  echo "==> pytest platform_db"
  (
    cd "${REPO_ROOT}"
    "${PYTHON_BIN}" -m pytest platform_db/tests
  )
fi

if [[ -d "infra/scripts/tests" ]]; then
  echo "==> pytest infra/scripts"
  (
    cd "${REPO_ROOT}"
    "${PYTHON_BIN}" -m pytest infra/scripts/tests
  )
fi
