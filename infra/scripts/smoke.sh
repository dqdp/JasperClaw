#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ROOT_ENV_FILE="${ROOT_ENV_FILE:-.env}"
COMPOSE_BASE_FILE="${COMPOSE_BASE_FILE:-infra/compose/compose.yml}"
COMPOSE_OVERRIDE_FILE="${COMPOSE_OVERRIDE_FILE:-infra/compose/compose.prod.yml}"
APP_SERVICE_NAME="${APP_SERVICE_NAME:-agent-api}"
OPEN_WEBUI_SERVICE_NAME="${OPEN_WEBUI_SERVICE_NAME:-open-webui}"
WAIT_TIMEOUT_SECONDS="${WAIT_TIMEOUT_SECONDS:-180}"
DOCKER_BIN="${DOCKER_BIN:-docker}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

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
  local -a cmd=("$DOCKER_BIN" compose --env-file "$ROOT_ENV_FILE" -f "$COMPOSE_BASE_FILE")
  if [[ -n "$COMPOSE_OVERRIDE_FILE" ]]; then
    cmd+=(-f "$COMPOSE_OVERRIDE_FILE")
  fi
  cmd+=("$@")
  "${cmd[@]}"
}

SMOKE_SKIP_DOMAIN_CHECK_EFFECTIVE="${SMOKE_SKIP_DOMAIN_CHECK:-false}"
if is_truthy "$SMOKE_SKIP_DOMAIN_CHECK_EFFECTIVE"; then
  SMOKE_SKIP_DOMAIN_CHECK_EFFECTIVE="true"
else
  SMOKE_SKIP_DOMAIN_CHECK_EFFECTIVE="false"
fi

if [[ -n "${DOMAIN:-}" && "$SMOKE_SKIP_DOMAIN_CHECK_EFFECTIVE" != "true" ]]; then
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

SMOKE_CHECK_OPEN_WEBUI_VOICE_WIRING_EFFECTIVE="${SMOKE_CHECK_OPEN_WEBUI_VOICE_WIRING:-$SMOKE_CHECK_VOICE_EFFECTIVE}"
if is_truthy "$SMOKE_CHECK_OPEN_WEBUI_VOICE_WIRING_EFFECTIVE"; then
  SMOKE_CHECK_OPEN_WEBUI_VOICE_WIRING_EFFECTIVE="true"
else
  SMOKE_CHECK_OPEN_WEBUI_VOICE_WIRING_EFFECTIVE="false"
fi

compose exec -T \
  -e SMOKE_BASE_URL="http://127.0.0.1:8080" \
  -e SMOKE_TIMEOUT_SECONDS="$WAIT_TIMEOUT_SECONDS" \
  -e SMOKE_CHECK_VOICE="$SMOKE_CHECK_VOICE_EFFECTIVE" \
  -e SMOKE_CHECK_STT="$SMOKE_CHECK_STT_EFFECTIVE" \
  -e SMOKE_TTS_VOICE="$SMOKE_TTS_VOICE_EFFECTIVE" \
  "$APP_SERVICE_NAME" python - < infra/scripts/smoke-agent-api.py

if [[ "$SMOKE_CHECK_OPEN_WEBUI_VOICE_WIRING_EFFECTIVE" == "true" ]]; then
  SMOKE_TTS_VOICE="$SMOKE_TTS_VOICE_EFFECTIVE" \
  "${PYTHON_BIN}" infra/scripts/smoke-open-webui.py < <(
    compose exec -T "$OPEN_WEBUI_SERVICE_NAME" env
  )
fi

if [[ -n "${TELEGRAM_SMOKE_BASE_URL:-}" ]]; then
  "${PYTHON_BIN}" infra/scripts/smoke-telegram-ingress.py
fi
