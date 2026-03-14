#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
source "${REPO_ROOT}/infra/scripts/lib/release-logging.sh"

ROOT_ENV_FILE="${ROOT_ENV_FILE:-.env}"
COMPOSE_BASE_FILE="${COMPOSE_BASE_FILE:-infra/compose/compose.yml}"
COMPOSE_OVERRIDE_FILE="${COMPOSE_OVERRIDE_FILE:-}"
POSTGRES_SERVICE_NAME="${POSTGRES_SERVICE_NAME:-postgres}"
PLATFORM_DB_SERVICE_NAME="${PLATFORM_DB_SERVICE_NAME:-platform-db}"
BACKUP_BASENAME_PREFIX="${BACKUP_BASENAME_PREFIX:-assistant}"
RESTORE_DATABASE_NAME="${RESTORE_DATABASE_NAME:-assistant_restore_check}"
KEEP_ARTIFACTS_ON_SUCCESS="${KEEP_ARTIFACTS_ON_SUCCESS:-false}"

if [[ -f "$ROOT_ENV_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$ROOT_ENV_FILE"
  set +a
fi

# The compose topology interpolates these root env vars even when the drill only
# needs Postgres. Cheap defaults keep the drill runnable on a local machine.
: "${APP_VERSION:=dev}"
: "${GHCR_OWNER:=local}"
: "${POSTGRES_PASSWORD:=change-me}"
: "${INTERNAL_OPENAI_API_KEY:=test-internal-key}"
: "${WEBUI_SECRET_KEY:=test-webui-secret}"
: "${DOMAIN:=localhost}"

ARTIFACT_DIR_CREATED=0
ARTIFACT_DIR="${ARTIFACT_DIR:-}"
SCRIPT_SUCCEEDED=0
POSTGRES_WAS_RUNNING=0

compose() {
  local -a cmd=(docker compose --env-file "$ROOT_ENV_FILE" -f "$COMPOSE_BASE_FILE")
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

checksum_file() {
  local path="$1"
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$path"
  else
    shasum -a 256 "$path"
  fi
}

seed_restore_fixture() {
  compose exec -T "$POSTGRES_SERVICE_NAME" psql -U assistant -d assistant <<'SQL'
INSERT INTO conversations (id, public_profile, created_at, updated_at)
VALUES ('conv_restore_seed', 'assistant-v1', '2026-03-14T10:45:00Z', '2026-03-14T10:45:00Z')
ON CONFLICT (id) DO NOTHING;

INSERT INTO messages (id, conversation_id, message_index, role, content, source, created_at)
VALUES (
  'msg_restore_seed',
  'conv_restore_seed',
  0,
  'user',
  'Remember that my favorite color is blue.',
  'request_transcript',
  '2026-03-14T10:45:00Z'
)
ON CONFLICT (id) DO NOTHING;
SQL
}

write_backup_artifact() {
  compose exec -T "$POSTGRES_SERVICE_NAME" pg_dump -U assistant -d assistant -Fc > "$BACKUP_PATH"
}

validate_backup_dump() {
  docker run --rm \
    -v "${ARTIFACT_DIR}:/backup" \
    pgvector/pgvector:pg17 \
    pg_restore -l "/backup/$(basename "$BACKUP_PATH")" >/dev/null
}

recreate_restore_database() {
  compose exec -T "$POSTGRES_SERVICE_NAME" psql -U assistant -d postgres \
    -c "DROP DATABASE IF EXISTS ${RESTORE_DATABASE_NAME};"
  compose exec -T "$POSTGRES_SERVICE_NAME" psql -U assistant -d postgres \
    -c "CREATE DATABASE ${RESTORE_DATABASE_NAME};"
}

restore_backup_artifact() {
  cat "$BACKUP_PATH" | compose exec -T "$POSTGRES_SERVICE_NAME" \
    pg_restore -U assistant -d "$RESTORE_DATABASE_NAME" --clean --if-exists
}

cleanup() {
  set +e
  compose exec -T "$POSTGRES_SERVICE_NAME" psql -U assistant -d postgres \
    -c "DROP DATABASE IF EXISTS ${RESTORE_DATABASE_NAME};" >/dev/null 2>&1
  if [[ "$POSTGRES_WAS_RUNNING" -eq 0 ]]; then
    compose stop "$POSTGRES_SERVICE_NAME" >/dev/null 2>&1
  fi
  if [[ "$ARTIFACT_DIR_CREATED" -eq 1 && "$SCRIPT_SUCCEEDED" -eq 1 ]] && ! is_truthy "$KEEP_ARTIFACTS_ON_SUCCESS"; then
    rm -rf "$ARTIFACT_DIR"
  fi
}
trap cleanup EXIT

mkdir -p "$REPO_ROOT"
if [[ -z "$ARTIFACT_DIR" ]]; then
  ARTIFACT_DIR="$(mktemp -d /tmp/jasperclaw-backup-drill.XXXXXX)"
  ARTIFACT_DIR_CREATED=1
else
  mkdir -p "$ARTIFACT_DIR"
fi

if [[ -n "$(compose ps -q "$POSTGRES_SERVICE_NAME")" ]]; then
  POSTGRES_WAS_RUNNING=1
fi

log_info "Backup/restore env file: ${ROOT_ENV_FILE}"
log_info "Backup artifact prefix: ${BACKUP_BASENAME_PREFIX}"
log_info "Disposable restore database: ${RESTORE_DATABASE_NAME}"

run_logged_step "start postgres for restore drill" compose up -d "$POSTGRES_SERVICE_NAME"

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

run_logged_step "seed canonical transcript rows" seed_restore_fixture

BACKUP_ID="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP_PATH="${ARTIFACT_DIR}/${BACKUP_BASENAME_PREFIX}_${BACKUP_ID}.dump"
run_logged_step "write backup artifact" write_backup_artifact
checksum_file "$BACKUP_PATH" > "${BACKUP_PATH}.sha256"
printf '%s\n' "${APP_VERSION}" > "${BACKUP_PATH}.version"

run_logged_step "validate dump readability" validate_backup_dump

run_logged_step "recreate disposable restore database" recreate_restore_database
run_logged_step "restore backup into disposable database" restore_backup_artifact

schema_migrations_present="$(
  compose exec -T "$POSTGRES_SERVICE_NAME" psql -U assistant -d "$RESTORE_DATABASE_NAME" -At \
    -c "SELECT to_regclass('schema_migrations');"
)"
conversation_count="$(
  compose exec -T "$POSTGRES_SERVICE_NAME" psql -U assistant -d "$RESTORE_DATABASE_NAME" -At \
    -c "SELECT COUNT(*) FROM conversations;"
)"
seed_conversation_count="$(
  compose exec -T "$POSTGRES_SERVICE_NAME" psql -U assistant -d "$RESTORE_DATABASE_NAME" -At \
    -c "SELECT COUNT(*) FROM conversations WHERE id = 'conv_restore_seed';"
)"
seed_message_count="$(
  compose exec -T "$POSTGRES_SERVICE_NAME" psql -U assistant -d "$RESTORE_DATABASE_NAME" -At \
    -c "SELECT COUNT(*) FROM messages WHERE id = 'msg_restore_seed';"
)"

if [[ "$schema_migrations_present" != "schema_migrations" ]]; then
  echo "schema_migrations table missing after restore" >&2
  exit 1
fi
if [[ "$conversation_count" -lt 1 ]]; then
  echo "restored database contains no conversations" >&2
  exit 1
fi
if [[ "$seed_conversation_count" != "1" || "$seed_message_count" != "1" ]]; then
  echo "seed transcript rows missing after restore" >&2
  exit 1
fi

SCRIPT_SUCCEEDED=1
log_info "Backup/restore drill succeeded"
log_info "Artifact directory: $ARTIFACT_DIR"
log_info "Backup path: $BACKUP_PATH"
