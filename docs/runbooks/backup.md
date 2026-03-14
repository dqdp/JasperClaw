# Runbook: Backup

## Purpose

Define the canonical backup scope and the minimum repeatable backup procedure
for v1.

## Canonical backup target

The canonical backup target is the `assistant` Postgres database.

This includes canonical and derived backend state such as:

- transcript tables
- execution audit tables
- memory and retrieval tables
- Telegram delivery state stored in Postgres
- `schema_migrations`

## Explicitly out of scope

The following are not treated as the canonical backup target:

- Ollama model cache
- STT model cache
- TTS voice/model assets
- container images
- generated audio files
- temporary files
- Open WebUI local state
- deployment secrets

If any of those need separate retention, handle them with a different operator
procedure instead of pretending they are part of the database backup.

## Preconditions

- the target environment is running `postgres`
- the operator has database credentials with dump access
- enough local or remote storage exists for the dump artifact

## Recommended artifact format

Use PostgreSQL custom-format dumps:

- `pg_dump -Fc`

This preserves a restorable archive format and works well with later
`pg_restore` checks.

## Standard backup procedure

1. Create a timestamped backup directory on the operator host.
2. Export the `assistant` database from the running `postgres` container.
3. Record a checksum next to the dump artifact.
4. Record the deployed image version or git SHA alongside the dump.

Example:

```bash
mkdir -p backups
BACKUP_ID="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP_PATH="backups/assistant_${BACKUP_ID}.dump"
docker compose exec -T postgres \
  pg_dump -U assistant -d assistant -Fc > "${BACKUP_PATH}"
sha256sum "${BACKUP_PATH}" > "${BACKUP_PATH}.sha256"
printf '%s\n' "${APP_VERSION:-unknown}" > "${BACKUP_PATH}.version"
```

## Minimum validation

After creating the dump:

- confirm the dump file is non-empty
- confirm the checksum file exists
- run `pg_restore -l` against the dump to verify it is readable

Example:

```bash
test -s "${BACKUP_PATH}"
pg_restore -l "${BACKUP_PATH}" >/dev/null
```

## Success criteria

The backup step is complete when:

- a readable custom-format dump exists
- a checksum exists next to it
- the operator can identify which deployment version the backup corresponds to
