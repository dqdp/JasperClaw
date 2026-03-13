from dataclasses import dataclass
from pathlib import Path
from threading import Lock

import psycopg


@dataclass(frozen=True, slots=True)
class Migration:
    version: str
    sql: str


@dataclass(frozen=True, slots=True)
class MigrationStatus:
    applied_versions: tuple[str, ...]
    pending_versions: tuple[str, ...]

    @property
    def is_current(self) -> bool:
        return not self.pending_versions


def default_migrations_dir() -> Path:
    for ancestor in Path(__file__).resolve().parents:
        candidate = ancestor / "platform-db" / "migrations"
        if candidate.is_dir():
            return candidate
    raise FileNotFoundError("platform-db migration catalog not found")


class MigrationRunner:
    def __init__(self, database_url: str, migrations_dir: Path | None = None) -> None:
        self._database_url = database_url
        self._migrations_dir = migrations_dir or default_migrations_dir()
        self._lock = Lock()
        self._is_current = False

    def ensure_current(self) -> None:
        if self._is_current:
            return

        with self._lock:
            if self._is_current:
                return

            with psycopg.connect(self._database_url) as conn:
                with conn.transaction():
                    self._ensure_migration_table(conn)
                    applied_versions = self._load_applied_versions(conn)
                    for migration in self._discover_migrations():
                        if migration.version in applied_versions:
                            continue
                        self._apply_migration(conn, migration)

            self._is_current = True

    def status(self) -> MigrationStatus:
        discovered = self._discover_migrations()
        if self._is_current:
            versions = tuple(migration.version for migration in discovered)
            return MigrationStatus(applied_versions=versions, pending_versions=())

        with psycopg.connect(self._database_url) as conn:
            if not self._migration_table_exists(conn):
                return MigrationStatus(
                    applied_versions=(),
                    pending_versions=tuple(migration.version for migration in discovered),
                )
            applied_versions = self._load_applied_versions(conn)

        pending_versions = tuple(
            migration.version
            for migration in discovered
            if migration.version not in applied_versions
        )
        if not pending_versions:
            self._is_current = True
        return MigrationStatus(
            applied_versions=tuple(sorted(applied_versions)),
            pending_versions=pending_versions,
        )

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

    def _migration_table_exists(self, conn: psycopg.Connection) -> bool:
        with conn.cursor() as cur:
            cur.execute("SELECT to_regclass('schema_migrations')")
            row = cur.fetchone()
            return row is not None and row[0] is not None

    def _load_applied_versions(self, conn: psycopg.Connection) -> set[str]:
        with conn.cursor() as cur:
            cur.execute("SELECT version FROM schema_migrations ORDER BY version")
            return {row[0] for row in cur.fetchall()}

    def _discover_migrations(self) -> list[Migration]:
        return [
            Migration(version=path.stem, sql=path.read_text())
            for path in sorted(self._migrations_dir.glob("*.sql"))
        ]

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
