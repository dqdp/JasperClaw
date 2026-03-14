#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ROOT_ENV_FILE="${ROOT_ENV_FILE:-.env}"
COMPOSE_BASE_FILE="${COMPOSE_BASE_FILE:-infra/compose/compose.yml}"
COMPOSE_OVERRIDE_FILE="${COMPOSE_OVERRIDE_FILE:-infra/compose/compose.prod.yml}"
APP_SERVICE_NAME="${APP_SERVICE_NAME:-agent-api}"
WAIT_TIMEOUT_SECONDS="${WAIT_TIMEOUT_SECONDS:-180}"

source "${REPO_ROOT}/infra/scripts/lib/dotenv.sh"

if [[ -f "$ROOT_ENV_FILE" ]]; then
  dotenv_export_file "$ROOT_ENV_FILE"
fi

is_truthy() {
  case "${1:-}" in
    1|true|TRUE|True|yes|YES|Yes|on|ON|On)
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

compose() {
  local -a cmd=(docker compose --env-file "$ROOT_ENV_FILE" -f "$COMPOSE_BASE_FILE")
  if [[ -n "$COMPOSE_OVERRIDE_FILE" ]]; then
    cmd+=(-f "$COMPOSE_OVERRIDE_FILE")
  fi
  cmd+=("$@")
  "${cmd[@]}"
}

if [[ -n "${DOMAIN:-}" ]]; then
  curl -fsS -o /dev/null -H "Host: ${DOMAIN}" http://127.0.0.1/
fi

SMOKE_CHECK_VOICE_EFFECTIVE="${SMOKE_CHECK_VOICE:-${VOICE_ENABLED:-false}}"
if is_truthy "$SMOKE_CHECK_VOICE_EFFECTIVE"; then
  SMOKE_CHECK_VOICE_EFFECTIVE="true"
else
  SMOKE_CHECK_VOICE_EFFECTIVE="false"
fi

SMOKE_TTS_VOICE_EFFECTIVE="${SMOKE_TTS_VOICE:-${TTS_DEFAULT_VOICE:-assistant-default}}"
SMOKE_CHECK_STT_EFFECTIVE="${SMOKE_CHECK_STT:-${VOICE_ENABLED:-false}}"
if is_truthy "$SMOKE_CHECK_STT_EFFECTIVE"; then
  SMOKE_CHECK_STT_EFFECTIVE="true"
else
  SMOKE_CHECK_STT_EFFECTIVE="false"
fi

compose exec -T \
  -e SMOKE_BASE_URL="http://127.0.0.1:8080" \
  -e SMOKE_TIMEOUT_SECONDS="$WAIT_TIMEOUT_SECONDS" \
  -e SMOKE_CHECK_VOICE="$SMOKE_CHECK_VOICE_EFFECTIVE" \
  -e SMOKE_CHECK_STT="$SMOKE_CHECK_STT_EFFECTIVE" \
  -e SMOKE_TTS_VOICE="$SMOKE_TTS_VOICE_EFFECTIVE" \
  "$APP_SERVICE_NAME" python - < infra/scripts/smoke-agent-api.py

if [[ -n "${TELEGRAM_SMOKE_BASE_URL:-}" ]]; then
  PYTHON_BIN="${PYTHON_BIN:-python3}"
  "${PYTHON_BIN}" infra/scripts/smoke-telegram-ingress.py
fi
