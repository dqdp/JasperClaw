from pathlib import Path


class _FakeCursor:
    def __init__(self, connection):
        self._connection = connection
        self._rows = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        _ = exc_type, exc, tb
        return False

    def execute(self, sql, params=None):
        normalized = " ".join(sql.split())
        self._connection.executed.append((normalized, params))
        if normalized.startswith("SELECT to_regclass('schema_migrations')"):
            self._rows = [("schema_migrations",)] if self._connection.migration_table_exists else [(None,)]
        if normalized.startswith("SELECT version FROM schema_migrations"):
            self._rows = [(version,) for version in self._connection.applied_versions]
        elif normalized.startswith("INSERT INTO schema_migrations"):
            self._connection.applied_versions.append(params[0])
        elif normalized.startswith("CREATE TABLE IF NOT EXISTS schema_migrations"):
            self._connection.migration_table_exists = True

    def fetchall(self):
        return list(self._rows)

    def fetchone(self):
        return self._rows[0] if self._rows else None


class _FakeTransaction:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        _ = exc_type, exc, tb
        return False


class _FakeConnection:
    def __init__(self):
        self.executed = []
        self.applied_versions = []
        self.migration_table_exists = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        _ = exc_type, exc, tb
        return False

    def transaction(self):
        return _FakeTransaction()

    def cursor(self):
        return _FakeCursor(self)


def test_platform_runner_applies_pending_sql(monkeypatch, tmp_path: Path) -> None:
    from platform_db.runner import MigrationRunner

    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()
    (migrations_dir / "0001_initial.sql").write_text("CREATE TABLE test_table (id INTEGER);")
    fake_connection = _FakeConnection()

    monkeypatch.setattr(
        "platform_db.runner.psycopg.connect",
        lambda database_url: fake_connection,
    )

    runner = MigrationRunner(
        database_url="postgresql://assistant:change-me@postgres:5432/assistant",
        migrations_dir=migrations_dir,
    )
    runner.ensure_current()

    assert any(
        "CREATE TABLE IF NOT EXISTS schema_migrations" in statement
        for statement, _ in fake_connection.executed
    )
    assert any(
        "CREATE TABLE test_table (id INTEGER);" in statement
        for statement, _ in fake_connection.executed
    )
    assert (
        "INSERT INTO schema_migrations (version) VALUES (%s)",
        ("0001_initial",),
    ) in fake_connection.executed


def test_default_migrations_dir_points_to_platform_db_catalog() -> None:
    from platform_db.runner import default_migrations_dir

    migrations_dir = default_migrations_dir()

    assert migrations_dir.name == "migrations"
    assert migrations_dir.parent.name == "platform-db"
