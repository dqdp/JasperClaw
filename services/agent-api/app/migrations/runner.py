from dataclasses import dataclass
from pathlib import Path
from threading import Lock

import psycopg

from app.core.errors import APIError


@dataclass(frozen=True, slots=True)
class Migration:
    version: str
    sql: str


class MigrationRunner:
    def __init__(self, database_url: str, migrations_dir: Path | None = None) -> None:
        self._database_url = database_url
        self._migrations_dir = migrations_dir or Path(__file__).resolve().parent / "sql"
        self._lock = Lock()
        self._is_current = False

    def ensure_current(self) -> None:
        if self._is_current:
            return

        with self._lock:
            if self._is_current:
                return

            try:
                with psycopg.connect(self._database_url) as conn:
                    with conn.transaction():
                        self._ensure_migration_table(conn)
                        applied_versions = self._load_applied_versions(conn)
                        for migration in self._discover_migrations():
                            if migration.version in applied_versions:
                                continue
                            self._apply_migration(conn, migration)
            except psycopg.Error as exc:
                raise APIError(
                    status_code=503,
                    error_type="dependency_unavailable",
                    code="storage_unavailable",
                    message="Persistent storage unavailable",
                ) from exc

            self._is_current = True

    def _ensure_migration_table(self, conn: psycopg.Connection) -> None:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version TEXT PRIMARY KEY,
                    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )

    def _load_applied_versions(self, conn: psycopg.Connection) -> set[str]:
        with conn.cursor() as cur:
            cur.execute("SELECT version FROM schema_migrations ORDER BY version")
            return {row[0] for row in cur.fetchall()}

    def _discover_migrations(self) -> list[Migration]:
        migrations: list[Migration] = []
        for path in sorted(self._migrations_dir.glob("*.sql")):
            migrations.append(Migration(version=path.stem, sql=path.read_text()))
        return migrations

    def _apply_migration(self, conn: psycopg.Connection, migration: Migration) -> None:
        with conn.cursor() as cur:
            cur.execute(migration.sql)
            cur.execute(
                """
                INSERT INTO schema_migrations (version)
                VALUES (%s)
                """,
                (migration.version,),
            )
