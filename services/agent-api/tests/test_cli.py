from types import SimpleNamespace

from app import cli
from app.migrations.runner import MigrationStatus


def test_cli_migrate_applies_pending_versions(monkeypatch, capsys) -> None:
    class _FakeRunner:
        def __init__(self, database_url: str) -> None:
            self.database_url = database_url
            self.ensure_current_calls = 0

        def status(self) -> MigrationStatus:
            return MigrationStatus(
                applied_versions=("0001_initial_schema",),
                pending_versions=("0002_conversation_updates",),
            )

        def ensure_current(self) -> None:
            self.ensure_current_calls += 1

    fake_runner = _FakeRunner("postgresql://assistant:test@postgres:5432/assistant")

    monkeypatch.setattr(
        cli,
        "get_settings",
        lambda: SimpleNamespace(
            database_url="postgresql://assistant:test@postgres:5432/assistant"
        ),
    )
    monkeypatch.setattr(cli, "MigrationRunner", lambda database_url: fake_runner)

    assert cli.main(["migrate"]) == 0
    assert fake_runner.ensure_current_calls == 1
    assert "Applied migrations: 0002_conversation_updates" in capsys.readouterr().out


def test_cli_migrate_reports_current_schema(monkeypatch, capsys) -> None:
    class _FakeRunner:
        def __init__(self, database_url: str) -> None:
            self.database_url = database_url
            self.ensure_current_calls = 0

        def status(self) -> MigrationStatus:
            return MigrationStatus(
                applied_versions=("0001_initial_schema",),
                pending_versions=(),
            )

        def ensure_current(self) -> None:
            self.ensure_current_calls += 1

    fake_runner = _FakeRunner("postgresql://assistant:test@postgres:5432/assistant")

    monkeypatch.setattr(
        cli,
        "get_settings",
        lambda: SimpleNamespace(
            database_url="postgresql://assistant:test@postgres:5432/assistant"
        ),
    )
    monkeypatch.setattr(cli, "MigrationRunner", lambda database_url: fake_runner)

    assert cli.main(["migrate"]) == 0
    assert fake_runner.ensure_current_calls == 0
    assert "Database schema already current" in capsys.readouterr().out
