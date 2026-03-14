#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
source "${REPO_ROOT}/infra/scripts/lib/release-logging.sh"

ROOT_ENV_FILE="${ROOT_ENV_FILE:-.env}"
COMPOSE_BASE_FILE="${COMPOSE_BASE_FILE:-infra/compose/compose.yml}"
COMPOSE_OVERRIDE_FILE="${COMPOSE_OVERRIDE_FILE:-infra/compose/compose.ci.yml}"
POSTGRES_SERVICE_NAME="${POSTGRES_SERVICE_NAME:-postgres}"
AGENT_SERVICE_NAME="${AGENT_SERVICE_NAME:-agent-api}"
PLATFORM_DB_SERVICE_NAME="${PLATFORM_DB_SERVICE_NAME:-platform-db}"
FAKE_RUNTIME_SERVICES="${FAKE_RUNTIME_SERVICES:-ollama ollama-fake}"
KEEP_STACK_ON_SUCCESS="${KEEP_STACK_ON_SUCCESS:-false}"

CANDIDATE_APP_VERSION="${CANDIDATE_APP_VERSION:-candidate-proof}"
KNOWN_GOOD_APP_VERSION="${KNOWN_GOOD_APP_VERSION:-known-good-proof}"

if [[ -f "$ROOT_ENV_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$ROOT_ENV_FILE"
  set +a
fi

: "${DRILL_GHCR_OWNER:=local}"
: "${DRILL_POSTGRES_PASSWORD:=ci-smoke-postgres}"
: "${DRILL_INTERNAL_OPENAI_API_KEY:=ci-smoke-key}"
: "${DRILL_WEBUI_SECRET_KEY:=ci-smoke-webui-secret}"
: "${DRILL_DOMAIN:=}"

: "${CANDIDATE_AGENT_IMAGE_SOURCE:=ghcr.io/local/local-assistant-agent:dev}"
: "${KNOWN_GOOD_AGENT_IMAGE_SOURCE:=ghcr.io/test/local-assistant-agent:dev}"
: "${CANDIDATE_DB_IMAGE_SOURCE:=ghcr.io/local/local-assistant-db-admin:dev}"
: "${KNOWN_GOOD_DB_IMAGE_SOURCE:=ghcr.io/test/local-assistant-db-admin:dev}"

ROOT_ENV_TEMP_FILE="$(mktemp /tmp/jasperclaw-rollback-root.XXXXXX)"
SCRIPT_SUCCEEDED=0

compose() {
  local -a cmd=(docker compose --env-file "$ROOT_ENV_TEMP_FILE" -f "$COMPOSE_BASE_FILE")
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

write_root_env() {
  local app_version="$1"
  cat > "$ROOT_ENV_TEMP_FILE" <<EOF
GHCR_OWNER=${DRILL_GHCR_OWNER}
APP_VERSION=${app_version}
POSTGRES_PASSWORD=${DRILL_POSTGRES_PASSWORD}
INTERNAL_OPENAI_API_KEY=${DRILL_INTERNAL_OPENAI_API_KEY}
WEBUI_SECRET_KEY=${DRILL_WEBUI_SECRET_KEY}
DOMAIN=${DRILL_DOMAIN}
EOF
  export GHCR_OWNER="${DRILL_GHCR_OWNER}"
  export APP_VERSION="${app_version}"
  export POSTGRES_PASSWORD="${DRILL_POSTGRES_PASSWORD}"
  export INTERNAL_OPENAI_API_KEY="${DRILL_INTERNAL_OPENAI_API_KEY}"
  export WEBUI_SECRET_KEY="${DRILL_WEBUI_SECRET_KEY}"
  export DOMAIN="${DRILL_DOMAIN}"
}

require_image() {
  local image="$1"
  if ! docker image inspect "$image" >/dev/null 2>&1; then
    echo "missing required local image: $image" >&2
    exit 1
  fi
}

tag_release_images() {
  docker tag "$CANDIDATE_AGENT_IMAGE_SOURCE" \
    "ghcr.io/${DRILL_GHCR_OWNER}/local-assistant-agent:${CANDIDATE_APP_VERSION}"
  docker tag "$KNOWN_GOOD_AGENT_IMAGE_SOURCE" \
    "ghcr.io/${DRILL_GHCR_OWNER}/local-assistant-agent:${KNOWN_GOOD_APP_VERSION}"
  docker tag "$CANDIDATE_DB_IMAGE_SOURCE" \
    "ghcr.io/${DRILL_GHCR_OWNER}/local-assistant-db-admin:${CANDIDATE_APP_VERSION}"
  docker tag "$KNOWN_GOOD_DB_IMAGE_SOURCE" \
    "ghcr.io/${DRILL_GHCR_OWNER}/local-assistant-db-admin:${KNOWN_GOOD_APP_VERSION}"
}

run_candidate_smoke() {
  ROOT_ENV_FILE="$ROOT_ENV_TEMP_FILE" \
  COMPOSE_BASE_FILE="$COMPOSE_BASE_FILE" \
  COMPOSE_OVERRIDE_FILE="$COMPOSE_OVERRIDE_FILE" \
  APP_SERVICE_NAME="$AGENT_SERVICE_NAME" \
  WAIT_TIMEOUT_SECONDS=90 \
  bash "${REPO_ROOT}/infra/scripts/smoke.sh"
}

run_rollback_smoke() {
  ROOT_ENV_FILE="$ROOT_ENV_TEMP_FILE" \
  COMPOSE_BASE_FILE="$COMPOSE_BASE_FILE" \
  COMPOSE_OVERRIDE_FILE="$COMPOSE_OVERRIDE_FILE" \
  APP_SERVICE_NAME="$AGENT_SERVICE_NAME" \
  WAIT_TIMEOUT_SECONDS=90 \
  bash "${REPO_ROOT}/infra/scripts/smoke.sh"
}

cleanup() {
  set +e
  if [[ "$SCRIPT_SUCCEEDED" -eq 0 ]] || ! is_truthy "$KEEP_STACK_ON_SUCCESS"; then
    compose down -v >/dev/null 2>&1
  fi
  rm -f "$ROOT_ENV_TEMP_FILE"
}
trap cleanup EXIT

require_image "$CANDIDATE_AGENT_IMAGE_SOURCE"
require_image "$KNOWN_GOOD_AGENT_IMAGE_SOURCE"
require_image "$CANDIDATE_DB_IMAGE_SOURCE"
require_image "$KNOWN_GOOD_DB_IMAGE_SOURCE"

log_info "Rollback drill candidate image: ${CANDIDATE_AGENT_IMAGE_SOURCE}"
log_info "Rollback drill known-good image: ${KNOWN_GOOD_AGENT_IMAGE_SOURCE}"
log_info "Rollback env file: ${ROOT_ENV_FILE}"

run_logged_step "tag candidate and known-good images" tag_release_images

write_root_env "$CANDIDATE_APP_VERSION"
compose down -v >/dev/null 2>&1 || true
run_logged_step "start rollback drill foundation services" compose up -d --no-build "$POSTGRES_SERVICE_NAME" $FAKE_RUNTIME_SERVICES
POSTGRES_CONTAINER_ID="$(compose ps -q "$POSTGRES_SERVICE_NAME")"
log_info "Waiting for postgres health on container ${POSTGRES_CONTAINER_ID}"
for _ in $(seq 1 60); do
  health="$(docker inspect -f '{{.State.Health.Status}}' "$POSTGRES_CONTAINER_ID" 2>/dev/null || true)"
  if [[ "$health" == "healthy" ]]; then
    break
  fi
  sleep 1
done
if [[ "${health:-}" != "healthy" ]]; then
  echo "postgres did not become healthy in time" >&2
  exit 1
fi
run_logged_step "apply platform migrations" compose run --rm --no-deps "$PLATFORM_DB_SERVICE_NAME" python -m platform_db.cli migrate
run_logged_step "start candidate agent" compose up -d --no-build "$AGENT_SERVICE_NAME"

CANDIDATE_IMAGE="$(docker inspect -f '{{.Config.Image}}' "compose-${AGENT_SERVICE_NAME}-1")"
if [[ "$CANDIDATE_IMAGE" != "ghcr.io/${DRILL_GHCR_OWNER}/local-assistant-agent:${CANDIDATE_APP_VERSION}" ]]; then
  echo "candidate container did not start with expected image tag" >&2
  exit 1
fi

run_logged_step "smoke candidate release" run_candidate_smoke

write_root_env "$KNOWN_GOOD_APP_VERSION"
run_logged_step "switch agent to known-good image" compose up -d --no-build --no-deps "$AGENT_SERVICE_NAME"

ROLLBACK_IMAGE="$(docker inspect -f '{{.Config.Image}}' "compose-${AGENT_SERVICE_NAME}-1")"
if [[ "$ROLLBACK_IMAGE" != "ghcr.io/${DRILL_GHCR_OWNER}/local-assistant-agent:${KNOWN_GOOD_APP_VERSION}" ]]; then
  echo "rollback container did not switch to expected known-good image tag" >&2
  exit 1
fi

run_logged_step "smoke rollback target" run_rollback_smoke

SCRIPT_SUCCEEDED=1
log_info "Rollback drill succeeded"
log_info "Candidate image: $CANDIDATE_IMAGE"
log_info "Rollback image: $ROLLBACK_IMAGE"
