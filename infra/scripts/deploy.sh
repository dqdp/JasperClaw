#!/usr/bin/env bash
set -euo pipefail

ROOT_ENV_FILE="${ROOT_ENV_FILE:-.env}"
COMPOSE_BASE_FILE="${COMPOSE_BASE_FILE:-infra/compose/compose.yml}"
COMPOSE_OVERRIDE_FILE="${COMPOSE_OVERRIDE_FILE:-infra/compose/compose.prod.yml}"
DOCKER_BIN="${DOCKER_BIN:-docker}"
ENSURE_OLLAMA_SCRIPT="${ENSURE_OLLAMA_SCRIPT:-infra/scripts/ensure-ollama-models.sh}"
SMOKE_SCRIPT="${SMOKE_SCRIPT:-infra/scripts/smoke.sh}"

if [[ ! -f "$ROOT_ENV_FILE" ]]; then
  echo "Root env file not found: $ROOT_ENV_FILE" >&2
  exit 1
fi

set -a
# shellcheck disable=SC1090
source "$ROOT_ENV_FILE"
set +a

compose() {
  local -a cmd=("$DOCKER_BIN" compose --env-file "$ROOT_ENV_FILE" -f "$COMPOSE_BASE_FILE")
  if [[ -n "$COMPOSE_OVERRIDE_FILE" ]]; then
    cmd+=(-f "$COMPOSE_OVERRIDE_FILE")
  fi
  cmd+=("$@")
  "${cmd[@]}"
}

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

has_voice_profile() {
  local profiles="${1:-}"
  local profile
  local -a split_profiles=()
  if [[ -z "$profiles" ]]; then
    return 1
  fi
  IFS=',' read -r -a split_profiles <<<"$profiles"
  for profile in "${split_profiles[@]}"; do
    if [[ "$profile" == "voice" ]]; then
      return 0
    fi
  done
  return 1
}

require_env() {
  local name="$1"
  if [[ -z "${!name:-}" ]]; then
    echo "Required root env var is missing: $name" >&2
    exit 1
  fi
}

require_env APP_VERSION
require_env GHCR_OWNER
require_env POSTGRES_PASSWORD
require_env INTERNAL_OPENAI_API_KEY
require_env WEBUI_SECRET_KEY

voice_enabled=false
if is_truthy "${VOICE_ENABLED:-false}"; then
  voice_enabled=true
fi

voice_profile_enabled=false
if has_voice_profile "${COMPOSE_PROFILES:-}"; then
  voice_profile_enabled=true
fi

if [[ "$voice_enabled" != "$voice_profile_enabled" ]]; then
  echo "Invalid rollout contract: VOICE_ENABLED and COMPOSE_PROFILES=voice must be aligned" >&2
  exit 1
fi

deploy_services=(agent-api telegram-ingress open-webui caddy)
if [[ "$voice_enabled" == "true" ]]; then
  deploy_services+=(stt-service tts-service)
fi

compose pull
compose up -d postgres ollama
ROOT_ENV_FILE="$ROOT_ENV_FILE" \
COMPOSE_BASE_FILE="$COMPOSE_BASE_FILE" \
COMPOSE_OVERRIDE_FILE="$COMPOSE_OVERRIDE_FILE" \
bash "$ENSURE_OLLAMA_SCRIPT"
compose build platform-db
compose run --rm --no-deps platform-db python -m platform_db.cli migrate
compose up -d --remove-orphans "${deploy_services[@]}"
ROOT_ENV_FILE="$ROOT_ENV_FILE" \
COMPOSE_BASE_FILE="$COMPOSE_BASE_FILE" \
COMPOSE_OVERRIDE_FILE="$COMPOSE_OVERRIDE_FILE" \
bash "$SMOKE_SCRIPT"
