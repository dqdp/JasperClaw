#!/usr/bin/env bash
set -euo pipefail

ROOT_ENV_FILE="${ROOT_ENV_FILE:-.env}"
APP_ENV_FILE="${APP_ENV_FILE:-infra/env/app.env}"
COMPOSE_BASE_FILE="${COMPOSE_BASE_FILE:-infra/compose/compose.yml}"
COMPOSE_OVERRIDE_FILE="${COMPOSE_OVERRIDE_FILE:-}"
OLLAMA_SERVICE_NAME="${OLLAMA_SERVICE_NAME:-ollama}"
WAIT_TIMEOUT_SECONDS="${WAIT_TIMEOUT_SECONDS:-180}"

if [[ ! -f "$APP_ENV_FILE" ]]; then
  echo "App env file not found: $APP_ENV_FILE" >&2
  exit 1
fi

set -a
# shellcheck disable=SC1090
source "$APP_ENV_FILE"
set +a

compose() {
  local -a cmd=(docker compose --env-file "$ROOT_ENV_FILE" -f "$COMPOSE_BASE_FILE")
  if [[ -n "$COMPOSE_OVERRIDE_FILE" ]]; then
    cmd+=(-f "$COMPOSE_OVERRIDE_FILE")
  fi
  cmd+=("$@")
  "${cmd[@]}"
}

require_model_config() {
  local name="$1"
  local value="${!name:-}"
  if [[ -z "${value// }" ]]; then
    echo "Required Ollama model config is missing: $name" >&2
    exit 1
  fi
}

is_true() {
  case "${1,,}" in
    1|true|yes|on) return 0 ;;
    *) return 1 ;;
  esac
}

wait_for_ollama() {
  local deadline=$((SECONDS + WAIT_TIMEOUT_SECONDS))
  until compose exec -T "$OLLAMA_SERVICE_NAME" ollama list >/dev/null 2>&1; do
    if (( SECONDS >= deadline )); then
      echo "Timed out waiting for Ollama service $OLLAMA_SERVICE_NAME" >&2
      exit 1
    fi
    sleep 2
  done
}

require_model_config OLLAMA_CHAT_MODEL
require_model_config OLLAMA_FAST_CHAT_MODEL

required_models=("$OLLAMA_CHAT_MODEL" "$OLLAMA_FAST_CHAT_MODEL")
if is_true "${MEMORY_ENABLED:-false}"; then
  require_model_config OLLAMA_EMBED_MODEL
  required_models+=("$OLLAMA_EMBED_MODEL")
fi

wait_for_ollama

installed_models="$(
  compose exec -T "$OLLAMA_SERVICE_NAME" ollama list | awk 'NR > 1 { print $1 }'
)"

declare -A seen_models=()
for model in "${required_models[@]}"; do
  if [[ -n "${seen_models[$model]:-}" ]]; then
    continue
  fi
  seen_models["$model"]=1

  if grep -Fqx "$model" <<<"$installed_models"; then
    printf 'Ollama model already present: %s\n' "$model"
    continue
  fi

  printf 'Pulling missing Ollama model: %s\n' "$model"
  compose exec -T "$OLLAMA_SERVICE_NAME" ollama pull "$model"
  installed_models+=$'\n'"$model"
done
