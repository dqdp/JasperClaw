# Runbook: Restore

## Purpose

Define the minimum disposable restore drill for v1 database backups.

This runbook intentionally validates restore into a disposable database before
any production restore decision is made.

## Preconditions

- a backup artifact created with the backup runbook exists
- the operator has access to a running `postgres` container or another
  disposable Postgres instance
- the operator has credentials that can create and drop a temporary database
- the root Compose env used by the stack is loaded, or commands are prefixed
  with the required root variables such as `APP_VERSION`, `GHCR_OWNER`, and
  `POSTGRES_PASSWORD`

## Disposable restore target

Use a temporary database such as `assistant_restore_check`.

Do not validate restore by writing directly over the active `assistant`
database.

## Standard disposable restore drill

1. Ensure `postgres` is running.
2. Drop any previous disposable restore database.
3. Create a fresh disposable restore database.
4. Restore the dump into that disposable database.
5. Run a small sanity-check query set.
6. Drop the disposable database when validation is complete.

Example:

```bash
BACKUP_PATH="backups/assistant_YYYYMMDDTHHMMSSZ.dump"

docker compose exec -T postgres \
  psql -U assistant -d postgres \
  -c "DROP DATABASE IF EXISTS assistant_restore_check;"

docker compose exec -T postgres \
  psql -U assistant -d postgres \
  -c "CREATE DATABASE assistant_restore_check;"

cat "${BACKUP_PATH}" | docker compose exec -T postgres \
  pg_restore -U assistant -d assistant_restore_check --clean --if-exists
```

## Minimum validation checklist

Run all of the following checks against the disposable restored database:

- `schema_migrations` exists
- core transcript tables exist
- the database is queryable without restore errors

Example:

```bash
docker compose exec -T postgres \
  psql -U assistant -d assistant_restore_check <<'SQL'
SELECT to_regclass('schema_migrations');
SELECT to_regclass('conversations');
SELECT to_regclass('messages');
SELECT to_regclass('model_runs');
SELECT COUNT(*) AS conversation_count FROM conversations;
SELECT version FROM schema_migrations ORDER BY version;
SQL
```

## Cleanup

After the validation succeeds, drop the disposable restore database:

```bash
docker compose exec -T postgres \
  psql -U assistant -d postgres \
  -c "DROP DATABASE IF EXISTS assistant_restore_check;"
```

## Notes

- if the dump cannot be restored into a disposable database, do not treat the
  backup as valid
- if a future production restore is required, first complete this disposable
  drill and then use the validated artifact and procedure for the real restore
- this runbook validates database recoverability only; it does not replace the
  rollback runbook for container image regressions

## Reproducible drill helper

For a local end-to-end proof of the backup and disposable restore path, prefer:

```bash
bash infra/scripts/drill-backup-restore.sh
```
